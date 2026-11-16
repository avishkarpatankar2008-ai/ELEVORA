
import Image from "next/image";

export function Logo({
  className = "",
  size = 36,
  showWordmark = true,
}: {
  className?: string;
  size?: number;
  showWordmark?: boolean;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <Image
        src="/elevora-mark.png"
        alt="ELEVORA"
        width={size}
        height={size}
        priority
        draggable={false}
        className="shrink-0 object-contain"
      />

      {showWordmark && (
        <span className="text-[17px] font-bold tracking-tight text-ink">
          ELEVORA
        </span>
      )}
    </span>
  );
}
