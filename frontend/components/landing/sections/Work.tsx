import { WORK_CASES } from "../data";
import { Dot, Photo } from "../ui";

export function Work() {
  return (
    <section id="work" data-8b-section="work" aria-labelledby="work-title">
      <div className="work__plate" aria-hidden="true" />
      <div className="work__stage">
        <div className="work__head">
          <h2 className="m-text-3" id="work-title">
            Choose your challenge
            <Dot />
          </h2>
          <p className="m-text-5 work__lead">Explore five ways to prepare. Choose a practice scenario that matches your next interview.</p>
        </div>
        <div className="work__window">
          <ul className="work__track">
            {WORK_CASES.map((item) => (
              <li className="case" key={item.title}>
                <div className="case__media">
                  <Photo id={item.photo} className="case__img" />
                </div>
                <span className="m-badge case__tag">{item.tag}</span>
                <div className="case__text">
                  <h3 className="m-text-4 case__name">{item.title}</h3>
                  <p className="m-text-5 case__line">{item.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
