import { JOURNAL_PHOTOS, JOURNAL_STORIES } from "../data";
import { Dot, Photo } from "../ui";

export function Journal() {
  return (
    <section id="journal" data-8b-section="journal" aria-labelledby="journal-title">
      <div className="journal__head">
        <h2 className="m-text-3" id="journal-title" data-8b-motion="rise">
          Interview resources
          <Dot />
        </h2>
      </div>
      <div className="journal__body">
        <div className="journal__frame">
          {JOURNAL_PHOTOS.map((photo) => (
            <Photo id={photo} className="journal__shot" key={photo} />
          ))}
        </div>
        <ol className="journal__list">
          {JOURNAL_STORIES.map((story) => (
            <li className="story" key={story.title}>
              <p className="m-text-6 story__meta">
                <span>{story.kind}</span> · <time dateTime={story.date}>{story.topic}</time>
              </p>
              <h3 className="m-text-7">{story.title}</h3>
              <p className="m-text story__text">{story.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
