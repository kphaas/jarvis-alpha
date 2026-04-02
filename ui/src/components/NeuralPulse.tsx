import { useEffect, useRef } from "react";

interface Props {
  active: boolean;
}

export function NeuralPulse({ active }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const c = ctx;

    const W = 80;
    const H = 28;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;
    c.scale(dpr, dpr);

    const nodes = [
      { x: W * 0.12, y: H * 0.25 },
      { x: W * 0.12, y: H * 0.75 },
      { x: W * 0.38, y: H * 0.12 },
      { x: W * 0.38, y: H * 0.5  },
      { x: W * 0.38, y: H * 0.88 },
      { x: W * 0.65, y: H * 0.25 },
      { x: W * 0.65, y: H * 0.75 },
      { x: W * 0.88, y: H * 0.5  },
    ];

    const edges = [
      [0,2],[0,3],[0,4],[1,2],[1,3],[1,4],
      [2,5],[2,6],[3,5],[3,6],[4,5],[4,6],
      [5,7],[6,7],
    ];

    const r = 2.5;
    const pulse = nodes.map((_, i) => i * 0.7);

    function draw() {
      c.clearRect(0, 0, W, H);

      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const edgeBase   = dark ? "rgba(183,210,240,0.15)" : "rgba(55,138,221,0.12)";
      const edgeActive = dark ? "rgba(183,210,240,0.55)" : "rgba(55,138,221,0.5)";
      const nodeFill   = dark ? "rgba(183,210,240,0.2)"  : "rgba(55,138,221,0.1)";
      const nodeBright = dark ? "rgba(183,210,240,0.9)"  : "rgba(55,138,221,0.9)";
      const nodeRing   = dark ? "rgba(183,210,240,0.25)" : "rgba(55,138,221,0.2)";
      const nodeBorder = dark ? "rgba(183,210,240,0.4)"  : "rgba(55,138,221,0.35)";

      for (let i = 0; i < pulse.length; i++) pulse[i] += 0.06 + i * 0.003;

      edges.forEach(([a, b]) => {
        const combined = ((Math.sin(pulse[a]) + 1) / 2 + (Math.sin(pulse[b]) + 1) / 2) / 2;
        c.beginPath();
        c.moveTo(nodes[a].x, nodes[a].y);
        c.lineTo(nodes[b].x, nodes[b].y);
        c.strokeStyle = combined > 0.6 ? edgeActive : edgeBase;
        c.lineWidth   = combined > 0.6 ? 1 : 0.5;
        c.stroke();
      });

      nodes.forEach((n, i) => {
        const p = (Math.sin(pulse[i]) + 1) / 2;
        const bright = p > 0.75;
        if (bright) {
          c.beginPath();
          c.arc(n.x, n.y, r * 2.2, 0, Math.PI * 2);
          c.fillStyle = nodeRing;
          c.fill();
        }
        c.beginPath();
        c.arc(n.x, n.y, r, 0, Math.PI * 2);
        c.fillStyle = bright ? nodeBright : nodeFill;
        c.fill();
        c.beginPath();
        c.arc(n.x, n.y, r, 0, Math.PI * 2);
        c.strokeStyle = nodeBorder;
        c.lineWidth = 0.75;
        c.stroke();
      });

      rafRef.current = requestAnimationFrame(draw);
    }

    if (active) {
      rafRef.current = requestAnimationFrame(draw);
    } else {
      c.clearRect(0, 0, W, H);
    }

    return () => cancelAnimationFrame(rafRef.current);
  }, [active]);

  if (!active) return null;

  return (
    <canvas
      ref={canvasRef}
      style={{ display: "block", flexShrink: 0 }}
    />
  );
}
