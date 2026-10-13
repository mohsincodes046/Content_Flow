import Link from "next/link";
import { BRAND } from "../lib/Brand";

export default function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="brand-lockup">
      <div className="brand-symbol">
        <svg aria-hidden="true" viewBox="0 0 36 36" fill="none">
          <path d="M18 4.5 21.3 14.7 31.5 18l-10.2 3.3L18 31.5l-3.3-10.2L4.5 18l10.2-3.3L18 4.5Z" fill="currentColor" />
          <circle cx="27.5" cy="8.5" r="2.5" fill="#B9E6CC" />
        </svg>
      </div>
      <span className="brand-name">
        {BRAND.name}
      </span>
    </Link>
  );
}

