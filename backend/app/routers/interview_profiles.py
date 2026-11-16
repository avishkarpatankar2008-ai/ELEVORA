from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.deps import get_current_user
from app.database import get_database
from app.models.interview_profile import new_profile_document, profile_doc_to_out
from app.schemas.interview_profile import (
    InterviewProfileCreate,
    InterviewProfileOut,
    InterviewProfileUpdate,
)
from app.services.interview_profiles import get_visible_profile

router = APIRouter(prefix="/interview-profiles", tags=["interview-profiles"])


@router.post("", response_model=InterviewProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: InterviewProfileCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InterviewProfileOut:
    doc = new_profile_document(payload, created_by=str(current_user["_id"]), is_system=False)
    result = await db.interview_profiles.insert_one(doc)
    doc["_id"] = result.inserted_id
    return profile_doc_to_out(doc)


@router.get("", response_model=list[InterviewProfileOut])
async def list_profiles(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> list[InterviewProfileOut]:
    """System profiles (available to everyone) plus this user's own active
    custom profiles — never another user's custom profiles."""
    user_id = str(current_user["_id"])
    cursor = db.interview_profiles.find(
        {
            "isActive": True,
            "$or": [{"isSystem": True}, {"createdBy": user_id}],
        }
    ).sort([("isSystem", -1), ("name", 1)])
    return [profile_doc_to_out(doc) async for doc in cursor]


@router.get("/{profile_id}", response_model=InterviewProfileOut)
async def get_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InterviewProfileOut:
    doc = await get_visible_profile(db, profile_id, str(current_user["_id"]))
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview profile not found")
    return profile_doc_to_out(doc)


@router.patch("/{profile_id}", response_model=InterviewProfileOut)
async def update_profile(
    profile_id: str,
    payload: InterviewProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InterviewProfileOut:
    user_id = str(current_user["_id"])

    # Distinguish "doesn't exist / not yours" (404) from "exists but is a
    # protected system profile" (403) so the error is honest about why.
    visible = await get_visible_profile(db, profile_id, user_id)
    if not visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview profile not found")
    if visible.get("isSystem"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="System profiles can't be edited."
        )

    updates = payload.model_dump(exclude_unset=True)
    if updates:
        updates["updatedAt"] = datetime.now(timezone.utc)
        # Scoped to the caller's own custom profile at the database level too, so a
        # profile that changed owner/type between the check above and this write
        # can never be modified.
        result = await db.interview_profiles.update_one(
            {"_id": ObjectId(profile_id), "createdBy": user_id, "isSystem": {"$ne": True}},
            {"$set": updates},
        )
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Interview profile not found"
            )

    # Read back directly: PATCH {"isActive": false} deactivates the profile, after
    # which the visibility-filtered helpers return None (and this used to 500).
    doc = await db.interview_profiles.find_one({"_id": ObjectId(profile_id)})
    if doc is None:  # deleted concurrently
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview profile not found")
    return profile_doc_to_out(doc)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> None:
    user_id = str(current_user["_id"])

    visible = await get_visible_profile(db, profile_id, user_id)
    if not visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview profile not found")
    if visible.get("isSystem"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="System profiles can't be deleted."
        )

    # Soft delete: interviews that already reference this profileId (via
    # load_profile) keep working exactly as configured. Only its visibility
    # in the picker/list disappears.
    await db.interview_profiles.update_one(
        {"_id": ObjectId(profile_id)},
        {"$set": {"isActive": False, "updatedAt": datetime.now(timezone.utc)}},
    )
