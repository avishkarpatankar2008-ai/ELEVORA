import { FAQS } from "../data";
import { Dot } from "../ui";

export function Faq() {
  return (
    <section id="faq" data-8b-section="faq" aria-labelledby="faq-title">
      <h2 className="m-text-3 faq__title" id="faq-title" data-8b-motion="rise">
        Frequently asked questions
        <Dot />
      </h2>
      <div className="faq__list">
        {FAQS.map((item) => (
          <details className="faq__item" key={item.q}>
            <summary className="m-text-7">
              {item.q}
              <span className="faq__mark" aria-hidden="true" />
            </summary>
            <p className="m-text faq__answer">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
