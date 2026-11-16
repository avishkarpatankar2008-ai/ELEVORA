import { SERVICES } from "../data";
import { Dot, Photo } from "../ui";

export function Capabilities() {
  return (
    <section id="capabilities" data-8b-section="capabilities" aria-labelledby="capabilities-title">
      <div className="capabilities__head">
        <h2 className="m-text-3" id="capabilities-title" data-8b-motion="rise">
          What ELEVORA offers
          <Dot />
        </h2>
        <p className="m-text-5 capabilities__lead">Tools for interview preparation, from personalised practice to structured feedback and progress tracking.</p>
      </div>
      <ol className="capabilities__deck">
        {SERVICES.map((service) => (
          <li className="service m-surface" key={service.title}>
            <div className="service__text">
              <h3 className="m-text-4">{service.title}</h3>
              <p className="m-text-5 service__line">{service.text}</p>
              <ul className="service__tags">
                {service.tags.map((tag) => (
                  <li className="m-badge" key={tag}>
                    {tag}
                  </li>
                ))}
              </ul>
            </div>
            <div className="service__media" data-8b-motion="iris">
              <Photo id={service.photo} />
            </div>
            <span className="service__shade" aria-hidden="true" />
          </li>
        ))}
      </ol>
    </section>
  );
}
