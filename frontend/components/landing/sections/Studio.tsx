import { PrimaryMLink } from "../AuthLinks";
import { STUDIO_SHOTS, STUDIO_TOPICS } from "../data";
import { Dot, Photo } from "../ui";

export function Studio() {
  return (
    <section id="studio" data-8b-section="studio" aria-labelledby="studio-title">
      <div className="studio__head">
        <h2 className="m-text-3" id="studio-title">
          Inside ELEVORA
          <Dot />
        </h2>
        <p className="m-text-5 studio__lead" data-8b-motion="ink">
          ELEVORA brings interview practice, structured feedback, and progress tracking together in one focused workspace. Practise at your own pace, review your performance, and focus on the skills that matter for your next interview.
        </p>
      </div>
      <div className="studio__collage">
        {STUDIO_SHOTS.map((shot) => (
          <figure className={`shot shot--${shot.shape}`} key={shot.photo}>
            <Photo id={shot.photo} />
          </figure>
        ))}
        <div className="studio__roles">
          <h3 className="m-text-7" data-8b-motion="rise">
            Explore ELEVORA
            <Dot />
          </h3>
          <ul>
            {STUDIO_TOPICS.map((topic) => (
              <li className="role" key={topic}>
                <span className="m-text-7">{topic}</span>
              </li>
            ))}
          </ul>
          <PrimaryMLink />
        </div>
      </div>
    </section>
  );
}
