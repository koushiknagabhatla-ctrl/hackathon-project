import Link from "next/link";
import s from "./not-found.module.css";

/** 404. Oversized serif numerals on paper, one line, one way back. */
export default function NotFound() {
  return (
    <main className={s.wrap}>
      <div className={s.digits} aria-hidden="true">
        {["4", "0", "4"].map((d, i) => (
          <span key={i} className={s.mask}>
            <span className={s.digit} style={{ animationDelay: `${i * 95}ms` }}>
              {d}
            </span>
          </span>
        ))}
      </div>

      <p className={s.copy}>This page doesn&rsquo;t exist. The URL may be misspelled, or the page may have moved.</p>

      <Link className={s.back} href="/">
        <span>Return home</span>
      </Link>

      <h1 className="sr-only">404 — page not found</h1>
    </main>
  );
}
