/**
 * SyntheticBanner — invariant 9: synthetic is never presented as observed.
 * Hatched stripe, hard border, uppercase word, flask icon and an assertive
 * live region. It is deliberately impossible to mistake for chrome.
 *
 * Put it ABOVE the content it qualifies, on every surface that shows anything
 * with evidence_class "synthetic" / "synthetic-corroboration" or a principal
 * in the sim trust domain.
 *
 *   <SyntheticBanner scope="Simulation SIM-014" seed={42} />
 *   <SyntheticBanner scope="Counterfactual" detail="Not observed. Not actionable." />
 */

import { Icon } from "./Icon";
import s from "./ui.module.css";

export interface SyntheticBannerProps {
  /** What is synthetic, e.g. "Simulation SIM-014" or "This forecast surface". */
  scope: string;
  /** Seed / scenario id, shown so a run is reproducible. */
  seed?: number | string;
  detail?: string;
}

export function SyntheticBanner({ scope, seed, detail }: SyntheticBannerProps) {
  return (
    <div role="note" aria-label="Synthetic data warning" style={{ display: "grid", gap: 8 }}>
      <div className={s.syntheticStripe} aria-hidden="true" />
      <div className={s.synthetic}>
        <Icon name="synthetic" size={22} label="Synthetic" />
        <div>
          <div className={s.syntheticLabel}>Synthetic — not observed</div>
          <div className={s.syntheticBody}>
            {scope} is generated data from the sandbox twin. It is never evidence
            of the real city and cannot authorise a production action.
            {seed !== undefined && (
              <>
                {" "}
                <span className="num">Seed {seed}</span>.
              </>
            )}
            {detail ? ` ${detail}` : ""}
          </div>
        </div>
      </div>
      <div className={s.syntheticStripe} aria-hidden="true" />
    </div>
  );
}

export default SyntheticBanner;
