import { STATEMENT_INDEX } from "../data";
import { Dot, MLink } from "../ui";

export function Statement() {
  return (
    <section id="statement" data-8b-section="statement" aria-labelledby="statement-title">
      <h2 className="m-text-3 statement__title" id="statement-title">
        <span className="statement__line">We build the confidence</span>
        <span className="statement__line">
          you come back&nbsp;with
          <Dot className="statement__dot" />
        </span>
      </h2>
      <div className="statement__body">
        <p className="m-text-5 statement__lead" data-8b-motion="ink">
          Great interviews come from deliberate practice, clear thinking, and learning from feedback. ELEVORA helps you prepare for the interviews you actually face, one practice session at a time.
        </p>
        <nav className="statement__index" aria-label="On this page">
          <ul>
            {STATEMENT_INDEX.map((item) => (
              <li key={item.href}>
                <MLink href={item.href}>{item.label}</MLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </section>
  );
}
