import type { PhotoId } from "./photos";

/** In-page sections linked from the nav, the statement index and the footer. */
export const SECTION_LINKS = [
  { href: "#work", label: "Practice" },
  { href: "#capabilities", label: "Features" },
  { href: "#method", label: "How It Works" },
  { href: "#studio", label: "Our Platform" },
  { href: "#journal", label: "Resources" },
] as const;

export const ROUND_PHOTO: PhotoId = "photo-1754738381783-f9a2847bfef2";

export const STATEMENT_INDEX = [
  { href: "#work", label: "Start practising" },
  { href: "#capabilities", label: "Explore features" },
  { href: "#method", label: "How it works" },
  { href: "#studio", label: "Inside ELEVORA" },
  { href: "#journal", label: "Interview resources" },
  { href: "#contact", label: "Start an interview" },
] as const;

type Card = { photo: PhotoId; tag: string; title: string; text: string };

export const WORK_CASES: Card[] = [
  { photo: "photo-1620802090791-fd9420668913", tag: "Interview practice", title: "Technical Interviews", text: "Practise technical questions, explain your approach, and strengthen your problem-solving skills." },
  { photo: "photo-1713371690087-baafaf440240", tag: "Professional practice", title: "Behavioural Interviews", text: "Structure your experiences into clear answers using relevant examples and a logical approach." },
  { photo: "photo-1587241321921-91a834d6d191", tag: "Career preparation", title: "HR Interviews", text: "Prepare for common HR questions about your goals, strengths, experiences, and expectations." },
  { photo: "photo-1544213456-bc37cb97df74", tag: "Communication", title: "Communication Practice", text: "Practise explaining your ideas clearly, concisely, and confidently." },
  { photo: "photo-1614149162883-504ce4d13909", tag: "Personalised practice", title: "Custom Interviews", text: "Prepare for interviews tailored to your target role, experience level, and skills." },
];

export const PROGRESS_CARDS: Card[] = [
  { photo: "photo-1594386245199-289c2fe0bd0a", tag: "Progress", title: "Performance History", text: "Review completed interviews and track your progress over time." },
  { photo: "photo-1532713107108-dfb5d8d2fc42", tag: "Practice", title: "Consistent Practice", text: "Build a consistent routine with focused, repeatable interview sessions." },
  { photo: "photo-1658296777645-0f389d06867c", tag: "Feedback", title: "Answer Improvement", text: "Use feedback to recognise weak answers and improve your next attempt." },
  { photo: "photo-1558324190-c940eb141401", tag: "Preparation", title: "Role Preparation", text: "Prepare for different roles and interview formats as your goals evolve." },
  { photo: "photo-1641675301559-468f9f4ca037", tag: "Learning", title: "Skill Development", text: "Develop clearer explanations, stronger reasoning, and better interview responses." },
  { photo: "photo-1761234852163-23f2ededd04e", tag: "Privacy", title: "Responsible AI", text: "Keep interview preparation focused on useful feedback and responsible handling of your data." },
];

export const SERVICES: { photo: PhotoId; title: string; text: string; tags: string[] }[] = [
  { photo: "photo-1617825295690-28ae56c56135", title: "Personalised Interviews", text: "Prepare for the role, experience level, and interview format that matter to you.", tags: ["Role Selection", "Skill Focus", "Question Practice", "Interview Goals"] },
  { photo: "photo-1601972599720-36938d4ecd31", title: "AI Interview Practice", text: "Practise interview questions and receive structured feedback through ELEVORA's interview workflow.", tags: ["Question Generation", "Answer Submission", "Answer Evaluation", "Performance Reports"] },
  { photo: "photo-1720175646447-e37d994007fc", title: "Answer Feedback", text: "Understand your strengths, identify areas to improve, and use actionable feedback to prepare for your next interview.", tags: ["Answer Quality", "Clarity", "Structure", "Relevance"] },
  { photo: "photo-1512758017271-d7b84c2113f1", title: "Posture Insights", text: "Optional, consent-based posture indicators can help you review camera framing and physical alignment during practice.", tags: ["Posture Tracking", "Alignment", "Camera Framing", "Session Summary"] },
  { photo: "photo-1769675353367-e581059c7c43", title: "Responsible AI", text: "Practical AI-assisted preparation designed to support your learning, not replace your judgement.", tags: ["Interview Preparation", "Practice Sessions", "AI Feedback", "Continuous Learning"] },
];

export const METHOD_STEPS = [
  { title: "Prepare", text: "Choose your target role, experience level, skills, and interview preferences." },
  { title: "Practise", text: "Answer interview questions in a focused session and work through each response." },
  { title: "Review", text: "Review your results, understand your strengths, and identify specific areas for improvement." },
  { title: "Improve", text: "Use what you learned to prepare for the next session and continue improving over time." },
] as const;

/** Order matters: the collage CSS positions the five shots by :nth-child. */
export const STUDIO_SHOTS: { photo: PhotoId; shape: "wide" | "tall" }[] = [
  { photo: "photo-1787647559705-d2ad3322020e", shape: "wide" },
  { photo: "photo-1643373977342-73cfc7cc0c5e", shape: "tall" },
  { photo: "photo-1745434159123-4908d0b9df94", shape: "tall" },
  { photo: "photo-1787647560262-ebfcf6c5f979", shape: "wide" },
  { photo: "photo-1623652653308-d49d335c92eb", shape: "wide" },
];

export const STUDIO_TOPICS = ["Technical Interview Practice", "Behavioural Interview Practice", "Personalised Interview Preparation"] as const;

/** Frame photos and stories are paired by index (the frame swaps as each story scrolls in). */
export const JOURNAL_PHOTOS: PhotoId[] = [
  "photo-1769755409781-9e8924c57362",
  "photo-1783094269325-4ba186e8e01b",
  "photo-1581080247486-57989c1f14ab",
  "photo-1542626991-cbc4e32524cc",
];

export const JOURNAL_STORIES = [
  { kind: "Guide", topic: "Interview Preparation", date: "2026-10-01", title: "How to Prepare for Your Next Interview", text: "Learn how to research a role, prepare relevant examples, and practise answering common interview questions." },
  { kind: "Guide", topic: "Answer Quality", date: "2026-09-18", title: "How to Structure Strong Interview Answers", text: "Explore practical ways to organise your answers, explain your reasoning, and communicate relevant experience." },
  { kind: "Guide", topic: "Communication", date: "2026-08-30", title: "How to Communicate Clearly Under Pressure", text: "Learn how concise explanations and structured thinking can make your interview responses easier to follow." },
  { kind: "Guide", topic: "Practice", date: "2026-08-04", title: "Why Repeated Interview Practice Matters", text: "Understand how deliberate practice, feedback, and reflection can help you prepare more effectively." },
] as const;

export const FAQS = [
  { q: "Who can use ELEVORA?", a: "ELEVORA is designed for people preparing for interviews across different roles and experience levels. Choose the interview practice that fits your goals." },
  { q: "How does an interview session work?", a: "Choose your interview preferences, practise answering questions, and review the available feedback and results after your session." },
  { q: "Can I practise for different roles?", a: "Use the available interview setup options to prepare for different roles, skills, and interview scenarios." },
  { q: "Is posture analysis mandatory?", a: "No. Posture analysis is optional and consent-based. You can practise without enabling your camera." },
  { q: "Does ELEVORA guarantee interview success?", a: "No platform can guarantee an interview outcome. ELEVORA is designed to help you practise, review feedback, and prepare more effectively." },
] as const;
