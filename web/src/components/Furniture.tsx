/** Мебель тонкими линиями: без неё план читается как набор пустых прямоугольников.
 *  Координаты абсолютные — комнаты на плане стоят на фиксированных местах. */

const shapes: Record<string, React.ReactNode> = {
  living: (
    <>
      <ellipse cx="300" cy="250" rx="120" ry="74" className="rug" />
      <rect x="70" y="150" width="132" height="180" rx="10" />
      <line x1="70" y1="210" x2="202" y2="210" />
      <line x1="70" y1="270" x2="202" y2="270" />
      <rect x="248" y="212" width="104" height="58" rx="8" />
      <rect x="524" y="168" width="12" height="116" rx="4" />
      <line x1="530" y1="140" x2="530" y2="168" />
      <rect x="410" y="70" width="150" height="16" rx="5" />
    </>
  ),
  bedroom: (
    <>
      <rect x="792" y="96" width="196" height="228" rx="12" />
      <rect x="806" y="110" width="78" height="34" rx="8" />
      <rect x="896" y="110" width="78" height="34" rx="8" />
      <line x1="792" y1="188" x2="988" y2="188" />
      <rect x="740" y="112" width="40" height="40" rx="6" />
      <rect x="1000" y="112" width="40" height="40" rx="6" />
      <rect x="1064" y="80" width="76" height="200" rx="8" />
      <line x1="1102" y1="80" x2="1102" y2="280" />
    </>
  ),
  kitchen: (
    <>
      <rect x="62" y="428" width="72" height="248" rx="8" />
      <line x1="62" y1="500" x2="134" y2="500" />
      <line x1="62" y1="572" x2="134" y2="572" />
      <circle cx="98" cy="640" r="22" />
      <circle cx="252" cy="596" r="48" />
      <rect x="196" y="700" width="112" height="14" rx="5" />
    </>
  ),
  hall: (
    <>
      <rect x="436" y="430" width="56" height="168" rx="7" />
      <line x1="464" y1="430" x2="464" y2="598" />
      <rect x="596" y="440" width="66" height="26" rx="6" />
      <path d="M470 780 A 84 84 0 0 0 554 696" className="door" />
      <line x1="470" y1="780" x2="554" y2="780" className="door" />
    </>
  ),
  bath: (
    <>
      <rect x="716" y="430" width="86" height="152" rx="18" />
      <circle cx="759" cy="466" r="6" />
      <circle cx="838" cy="470" r="24" />
      <rect x="820" y="620" width="46" height="62" rx="8" />
    </>
  ),
  study: (
    <>
      <rect x="920" y="428" width="184" height="66" rx="7" />
      <circle cx="1012" cy="546" r="30" />
      <rect x="1112" y="428" width="30" height="196" rx="5" />
      <line x1="1112" y1="494" x2="1142" y2="494" />
      <line x1="1112" y1="560" x2="1142" y2="560" />
      <rect x="946" y="700" width="130" height="14" rx="5" />
    </>
  ),
}

export function Furniture({ roomId }: { roomId: string }) {
  return <g className="furniture">{shapes[roomId] ?? null}</g>
}
