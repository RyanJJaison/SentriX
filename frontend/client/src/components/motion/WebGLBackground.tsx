import React, { useEffect, useRef } from "react";

interface WebGLBackgroundProps {
  opacity?: number;
  className?: string;
}

export function WebGLBackground({ opacity = 0.85, className = "" }: WebGLBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    // Mouse tracking with smooth spring easing
    const mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };
    // Scroll tracking
    let scrollY = window.scrollY;
    let targetScrollY = scrollY;

    const onResize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };

    const onMouseMove = (e: MouseEvent) => {
      mouse.targetX = (e.clientX / width - 0.5) * 2;
      mouse.targetY = (e.clientY / height - 0.5) * 2;
    };

    const onScroll = () => {
      targetScrollY = window.scrollY;
    };

    window.addEventListener("resize", onResize);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("scroll", onScroll, { passive: true });

    // 3D Geometry: Cryptographic Icosahedron / Geodesic Sphere Vertices
    const phi = (1 + Math.sqrt(5)) / 2;
    const baseVertices: [number, number, number][] = [
      [-1, phi, 0],
      [1, phi, 0],
      [-1, -phi, 0],
      [1, -phi, 0],
      [0, -1, phi],
      [0, 1, phi],
      [0, -1, -phi],
      [0, 1, -phi],
      [phi, 0, -1],
      [phi, 0, 1],
      [-phi, 0, -1],
      [-phi, 0, 1],
    ];

    // Normalize vertices to unit sphere
    const vertices = baseVertices.map(([x, y, z]) => {
      const len = Math.sqrt(x * x + y * y + z * z);
      return [x / len, y / len, z / len] as [number, number, number];
    });

    // Outer lattice ring nodes
    const ringNodes: [number, number, number][] = [];
    const ringCount = 24;
    for (let i = 0; i < ringCount; i++) {
      const theta = (i / ringCount) * Math.PI * 2;
      ringNodes.push([Math.cos(theta) * 1.5, Math.sin(theta) * 1.5, Math.sin(theta * 3) * 0.3]);
    }

    // Floating Data Particles (Ambient dust)
    const particleCount = 75;
    const particles: { x: number; y: number; z: number; size: number; speed: number; pulse: number }[] = [];
    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: (Math.random() - 0.5) * 4,
        y: (Math.random() - 0.5) * 4,
        z: (Math.random() - 0.5) * 4,
        size: Math.random() * 1.6 + 0.5,
        speed: Math.random() * 0.002 + 0.001,
        pulse: Math.random() * Math.PI * 2,
      });
    }

    // Connect vertices within threshold
    const edges: [number, number][] = [];
    for (let i = 0; i < vertices.length; i++) {
      for (let j = i + 1; j < vertices.length; j++) {
        const dx = vertices[i][0] - vertices[j][0];
        const dy = vertices[i][1] - vertices[j][1];
        const dz = vertices[i][2] - vertices[j][2];
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < 1.2) {
          edges.push([i, j]);
        }
      }
    }

    let rotX = 0.2;
    let rotY = 0.3;
    let rotZ = 0.1;
    let pulseTime = 0;

    // Render loop
    const render = () => {
      // Ease mouse and scroll
      mouse.x += (mouse.targetX - mouse.x) * 0.05;
      mouse.y += (mouse.targetY - mouse.y) * 0.05;
      scrollY += (targetScrollY - scrollY) * 0.08;

      ctx.clearRect(0, 0, width, height);

      // Base auto-rotation influenced by cursor and scroll
      rotY += 0.004 + mouse.x * 0.005;
      rotX += 0.002 + mouse.y * 0.005;
      rotZ = scrollY * 0.0008;
      pulseTime += 0.025;

      const scale = Math.min(width, height) * 0.28;
      // Center position shifted slightly right/responsive like Alche hero
      const centerX = width * 0.55 + mouse.x * 30;
      const centerY = height * 0.48 - Math.min(scrollY * 0.15, height * 0.4) + mouse.y * 30;

      // 3D rotation matrix application
      const cosY = Math.cos(rotY);
      const sinY = Math.sin(rotY);
      const cosX = Math.cos(rotX);
      const sinX = Math.sin(rotX);
      const cosZ = Math.cos(rotZ);
      const sinZ = Math.sin(rotZ);

      const project = (x: number, y: number, z: number): [number, number, number] => {
        // Rotate Y
        let x1 = x * cosY - z * sinY;
        let z1 = z * cosY + x * sinY;

        // Rotate X
        let y2 = y * cosX - z1 * sinX;
        let z2 = z1 * cosX + y * sinX;

        // Rotate Z
        let x3 = x1 * cosZ - y2 * sinZ;
        let y3 = y2 * cosZ + x1 * sinZ;

        // Perspective camera
        const distance = 3.2;
        const fov = 2.4 / (distance - z2);
        return [centerX + x3 * scale * fov, centerY + y3 * scale * fov, z2];
      };

      // 1. Draw Ambient Data Dust Particles
      ctx.save();
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.pulse += 0.03;
        p.y += p.speed;
        if (p.y > 2) p.y = -2;

        const [px, py, pz] = project(p.x, p.y, p.z);
        const alpha = Math.max(0.08, (pz + 1.5) / 3) * (0.5 + 0.5 * Math.sin(p.pulse));
        ctx.fillStyle = `rgba(45, 212, 191, ${alpha * 0.45})`;
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // 2. Draw Outer Orbit Ring (Alche gyroscopic hud style)
      ctx.save();
      ctx.strokeStyle = "rgba(45, 212, 191, 0.12)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 7]);
      ctx.beginPath();
      for (let i = 0; i < ringNodes.length; i++) {
        const [rx, ry] = project(ringNodes[i][0], ringNodes[i][1], ringNodes[i][2]);
        if (i === 0) ctx.moveTo(rx, ry);
        else ctx.lineTo(rx, ry);
      }
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();

      // 3. Project 3D Lattice Vertices
      const projected = vertices.map(([x, y, z]) => {
        // Breathing pulse effect
        const breath = 1 + 0.04 * Math.sin(pulseTime);
        return project(x * breath, y * breath, z * breath);
      });

      // 4. Draw Lattice Edges with Depth Shading
      ctx.save();
      for (let i = 0; i < edges.length; i++) {
        const [i1, i2] = edges[i];
        const p1 = projected[i1];
        const p2 = projected[i2];
        const avgZ = (p1[2] + p2[2]) / 2;

        // Depth alpha
        const alpha = Math.max(0.06, Math.min(0.7, (avgZ + 1.2) * 0.4));
        const gradient = ctx.createLinearGradient(p1[0], p1[1], p2[0], p2[1]);
        gradient.addColorStop(0, `rgba(45, 212, 191, ${alpha})`);
        gradient.addColorStop(0.5, `rgba(167, 243, 224, ${alpha * 1.3})`);
        gradient.addColorStop(1, `rgba(127, 119, 221, ${alpha * 0.6})`);

        ctx.strokeStyle = gradient;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(p1[0], p1[1]);
        ctx.lineTo(p2[0], p2[1]);
        ctx.stroke();
      }
      ctx.restore();

      // 5. Draw Vertices (Glowing Nodes)
      for (let i = 0; i < projected.length; i++) {
        const [vx, vy, vz] = projected[i];
        const nodeAlpha = Math.max(0.2, (vz + 1.2) * 0.55);
        const nodeRadius = Math.max(2, (vz + 2) * 2.2);

        // Core dot
        ctx.fillStyle = `rgba(238, 255, 250, ${nodeAlpha})`;
        ctx.beginPath();
        ctx.arc(vx, vy, nodeRadius, 0, Math.PI * 2);
        ctx.fill();

        // Outer glow aura
        ctx.fillStyle = `rgba(45, 212, 191, ${nodeAlpha * 0.35})`;
        ctx.beginPath();
        ctx.arc(vx, vy, nodeRadius * 2.5, 0, Math.PI * 2);
        ctx.fill();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <div
      className={`webgl-background-layer ${className}`}
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        zIndex: 0,
        opacity,
        overflow: "hidden",
      }}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />
    </div>
  );
}

export default WebGLBackground;
