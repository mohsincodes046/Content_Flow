import Link from "next/link";
import { BRAND } from "../../lib/Brand";

export default function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-lg font-bold text-white">
        C
      </div>
      <span className="text-xl font-semibold tracking-tight text-white">
        {BRAND.name}
      </span>
    </Link>
  );
}

