import { PROGRESS_CARDS } from "../data";
import { Dot, Photo } from "../ui";

export function Again() {
  return (
    <section id="again" data-8b-section="again" aria-labelledby="again-title">
      <div className="again__stage">
        <div className="again__head">
          <h2 className="m-text-3" id="again-title">
            Progress, not one-off practice
            <Dot />
          </h2>
          <p className="m-text-5 again__lead">
            Every practice session is an opportunity to learn. Review your performance, identify improvement areas, and keep building your interview skills.
          </p>
        </div>
        <div className="again__swing">
          <ul className="again__wheel">
            {PROGRESS_CARDS.map((item) => (
              <li className="partner" key={item.title}>
                <div className="partner__card">
                  <Photo id={item.photo} className="partner__img" />
                  <div className="partner__text">
                    <span className="m-badge partner__year">{item.tag}</span>
                    <h3 className="m-text-4 partner__name">{item.title}</h3>
                    <p className="m-text partner__line">{item.text}</p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
