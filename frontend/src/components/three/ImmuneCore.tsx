import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { MutableRefObject, ReactNode } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useLiveRisk } from '../../data/provider';

// Signature 3D piece: a geometric "immune core" — a wireframe icosahedron
// shield with agent nodes orbiting as a living network and a particle field
// that all breathe with the live risk score. See CLAUDE.md §6 for guardrails.

const AGENT_NODES = 8;
const PARTICLES = 620;

interface Palette {
    green: THREE.Color;
    amber: THREE.Color;
    red: THREE.Color;
    accent: THREE.Color;
}

function readVarColor(name: string, fallback: string): THREE.Color {
    if (typeof window === 'undefined') return new THREE.Color(fallback);
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    try {
        return new THREE.Color(value || fallback);
    } catch {
        return new THREE.Color(fallback);
    }
}

// Read brand/semantic colours from the active theme so the hero re-tints on
// light/dark toggle (semantic green/amber/red darken on light for visibility).
function useThemePalette(): Palette {
    const read = (): Palette => ({
        green: readVarColor('--green', '#3fd68b'),
        amber: readVarColor('--amber', '#f0b429'),
        red: readVarColor('--red', '#f6465d'),
        accent: readVarColor('--accent-ink', '#97fce4'),
    });
    const [palette, setPalette] = useState<Palette>(read);
    useEffect(() => {
        const observer = new MutationObserver(() => setPalette(read()));
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme'],
        });
        return () => observer.disconnect();
    }, []);
    return palette;
}

function riskColorInto(target: THREE.Color, risk: number, palette: Palette): void {
    if (risk < 0.5) target.copy(palette.green).lerp(palette.amber, risk / 0.5);
    else target.copy(palette.amber).lerp(palette.red, (risk - 0.5) / 0.5);
}

function hasWebGL(): boolean {
    try {
        const canvas = document.createElement('canvas');
        return (
            !!window.WebGLRenderingContext &&
            !!(canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
        );
    } catch {
        return false;
    }
}

interface SceneProps {
    riskRef: MutableRefObject<number>;
    reduced: boolean;
    compact: boolean;
    palette: Palette;
}

const Scene = memo(function Scene({ riskRef, reduced, compact, palette }: SceneProps) {
    const group = useRef<THREE.Group>(null);
    const core = useRef<THREE.Mesh>(null);
    const coreMat = useRef<THREE.MeshBasicMaterial>(null);
    const innerMat = useRef<THREE.MeshBasicMaterial>(null);
    const lineMat = useRef<THREE.LineBasicMaterial>(null);
    const pointsMat = useRef<THREE.PointsMaterial>(null);
    const nodes = useRef<THREE.Group>(null);
    const color = useMemo(() => new THREE.Color(), []);

    const geometry = useMemo(() => {
        const ringRadius = 2.05;
        const nodePositions: [number, number, number][] = [];
        for (let i = 0; i < AGENT_NODES; i += 1) {
            const a = (i / AGENT_NODES) * Math.PI * 2;
            nodePositions.push([Math.cos(a) * ringRadius, Math.sin(a * 2) * 0.28, Math.sin(a) * ringRadius]);
        }
        const edgeList: number[] = [];
        nodePositions.forEach((n, i) => {
            edgeList.push(0, 0, 0, n[0], n[1], n[2]);
            const next = nodePositions[(i + 1) % AGENT_NODES];
            edgeList.push(n[0], n[1], n[2], next[0], next[1], next[2]);
        });
        const count = compact ? 320 : PARTICLES;
        const particlePositions = new Float32Array(count * 3);
        for (let i = 0; i < count; i += 1) {
            const u = Math.random();
            const v = Math.random();
            const theta = u * Math.PI * 2;
            const phi = Math.acos(2 * v - 1);
            const rad = 2.6 + Math.random() * 1.1;
            particlePositions[i * 3] = Math.sin(phi) * Math.cos(theta) * rad;
            particlePositions[i * 3 + 1] = Math.cos(phi) * rad * 0.78;
            particlePositions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * rad;
        }
        return { nodePositions, edges: new Float32Array(edgeList), particles: particlePositions };
    }, [compact]);

    useFrame((state, delta) => {
        const risk = riskRef.current;
        riskColorInto(color, risk, palette);
        const t = state.clock.elapsedTime;
        const spin = reduced ? 0 : delta * (0.08 + risk * 0.22);
        if (group.current) group.current.rotation.y += spin;
        if (core.current) {
            core.current.scale.setScalar(1 + Math.sin(t * 1.6) * 0.03 * (0.4 + risk));
            if (!reduced) core.current.rotation.x += delta * 0.05;
        }
        if (coreMat.current) coreMat.current.color.copy(color);
        if (innerMat.current) {
            innerMat.current.color.copy(color);
            innerMat.current.opacity = 0.1 + risk * 0.2;
        }
        if (lineMat.current) {
            lineMat.current.color.copy(color);
            lineMat.current.opacity = 0.16 + risk * 0.42;
        }
        if (pointsMat.current) {
            pointsMat.current.color.copy(color);
            pointsMat.current.size = 0.018 + risk * 0.03;
        }
        if (nodes.current) {
            nodes.current.children.forEach((node, i) => {
                node.scale.setScalar(1 + Math.sin(t * 2 + i) * 0.22 * (0.4 + risk));
            });
        }
    });

    return (
        <group ref={group}>
            <mesh ref={core}>
                <icosahedronGeometry args={[1.15, 1]} />
                <meshBasicMaterial ref={coreMat} wireframe transparent opacity={0.5} />
            </mesh>
            <mesh>
                <icosahedronGeometry args={[0.78, 0]} />
                <meshBasicMaterial ref={innerMat} transparent opacity={0.16} />
            </mesh>
            <lineSegments>
                <bufferGeometry>
                    <bufferAttribute attach="attributes-position" args={[geometry.edges, 3]} />
                </bufferGeometry>
                <lineBasicMaterial ref={lineMat} transparent opacity={0.3} />
            </lineSegments>
            <group ref={nodes}>
                {geometry.nodePositions.map((position, i) => (
                    <mesh key={i} position={position}>
                        <sphereGeometry args={[0.07, 14, 14]} />
                        <meshBasicMaterial color={palette.accent} />
                    </mesh>
                ))}
            </group>
            <points>
                <bufferGeometry>
                    <bufferAttribute attach="attributes-position" args={[geometry.particles, 3]} />
                </bufferGeometry>
                <pointsMaterial
                    ref={pointsMat}
                    size={0.026}
                    transparent
                    opacity={0.6}
                    sizeAttenuation
                    depthWrite={false}
                />
            </points>
        </group>
    );
});

export function ImmuneCore({
    children,
    compact = false,
}: {
    children?: ReactNode;
    compact?: boolean;
}) {
    const risk = useLiveRisk();
    const riskRef = useRef(risk);
    riskRef.current = risk;
    const palette = useThemePalette();

    const [supported] = useState(hasWebGL);
    const reduced = useMemo(
        () =>
            typeof window !== 'undefined' && typeof window.matchMedia === 'function'
                ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
                : false,
        [],
    );
    const [frameloop, setFrameloop] = useState<'always' | 'never'>(() =>
        document.hidden || reduced ? 'never' : 'always',
    );

    useEffect(() => {
        const update = () => setFrameloop(document.hidden ? 'never' : reduced ? 'never' : 'always');
        document.addEventListener('visibilitychange', update);
        // Reduced motion: render one frame, then freeze.
        let timer: number | undefined;
        if (reduced) {
            setFrameloop('always');
            timer = window.setTimeout(() => setFrameloop('never'), 500);
        }
        return () => {
            document.removeEventListener('visibilitychange', update);
            if (timer) window.clearTimeout(timer);
        };
    }, [reduced]);

    return (
        <div className={`hero-three ${compact ? 'compact' : ''}`}>
            {supported ? (
                <Canvas
                    dpr={[1, 1.5]}
                    frameloop={frameloop}
                    camera={{ position: [0, 1.5, compact ? 5.8 : 5.2], fov: 45 }}
                    gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
                >
                    <Scene riskRef={riskRef} reduced={reduced} compact={compact} palette={palette} />
                </Canvas>
            ) : (
                <div className="three-fallback">Immune core (3D unavailable)</div>
            )}
            {children}
        </div>
    );
}
