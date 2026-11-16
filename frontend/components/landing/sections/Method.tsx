import { METHOD_STEPS } from "../data";
import { Dot } from "../ui";

const STATIONS = [
  { x: 0, y: -1 },
  { x: 1, y: 0 },
  { x: 0, y: 1 },
  { x: -1, y: 0 },
];

export function Method() {
  return (
    <section id="method" data-8b-section="method" aria-labelledby="method-title">
      <div className="method__head">
        <h2 className="m-text-3" id="method-title" data-8b-motion="rise">
          How ELEVORA works
          <Dot />
        </h2>
        <p className="m-text-5 method__lead" data-8b-motion="ink">
          Every interview practice session follows a simple learning cycle. Prepare, practise, review your feedback, and repeat with a clearer goal.
        </p>
      </div>
      <div className="method__body">
        <div className="method__ring" aria-hidden="true">
          <svg className="method__svg" viewBox="0 0 400 400">
            <circle className="method__track" cx="200" cy="200" r="170" />
            <circle className="method__arc" cx="200" cy="200" r="170" pathLength={1} strokeDasharray="1 1" strokeDashoffset={0} />
          </svg>
          {STATIONS.map((s) => (
            <span className="method__station" key={`${s.x}${s.y}`} style={{ "--x": s.x, "--y": s.y } as React.CSSProperties} />
          ))}
          <span className="method__arm">
            <span className="method__runner" />
          </span>
        </div>
        <ol className="method__steps">
          {METHOD_STEPS.map((step) => (
            <li className="step" key={step.title}>
              <h3 className="m-text-4">{step.title}</h3>
              <p className="m-text-5 step__text">{step.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
