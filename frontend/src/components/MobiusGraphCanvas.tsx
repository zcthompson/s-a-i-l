/**
 * MobiusGraphCanvas — the three.js renderer of the Customer Intelligence
 * visualization: a spatial neural network with category-hued node solids,
 * glow halos, network links with traveling pulses, manual
 * pointer orbit, and DOM-projected labels.
 *
 * View-only: layout comes from `lib/mobiusLayout`, colors from
 * `lib/mobiusPalette`. The scene is built once per projection (positions are
 * independent of the domain filter); hover/selection/filter changes are
 * lightweight material/visibility syncs, never scene rebuilds.
 *
 * Interaction: pointer orbit (drag), wheel zoom, click select, hover
 * highlight are mouse/touch driven; Escape (handled by the owner) clears the
 * selection. The surface is an enhancement — the owner provides the legend
 * and a visually-hidden node list as the accessible equivalent.
 *
 * Failure: if WebGL cannot be created (or the context is lost) the canvas
 * logs `[mobius] webgl unavailable` and calls `onUnavailable` so the owner
 * renders the 'visualization unavailable' card.
 */
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from 'react';
import * as THREE from 'three';
import type { RenderGraph, RenderLink } from '../lib/intelligenceGraph';
import { CATEGORY_STYLES, DATA_DOMAIN_ORDER, styleFor } from '../lib/intelligenceGraph';
import {
  MobiusNode,
  Vec3,
  buildMobiusLayout,
  buildSpokePoints,
  domainU,
  isCrossDomainLink,
} from '../lib/mobiusLayout';
import { MOBIUS_SURFACE, mobiusColor } from '../lib/mobiusPalette';

export const MOBIUS_WEBGL_MARKER = '[mobius] webgl unavailable';

export interface MobiusCanvasHandle {
  resetView: () => void;
}

interface Props {
  /** Full (unfiltered) projection — layout is stable under filtering. */
  graph: RenderGraph;
  /** Ids of nodes currently visible (domain filter). */
  visibleIds: Set<string>;
  hoveredId: string | null;
  selectedId: string | null;
  reducedMotion: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  onUnavailable: () => void;
}

const DEFAULT_VIEW = { azimuth: 0.5, elevation: 0.72, radius: 7.7 };
export const MAX_LIVE_PULSES = 120;

type PulseKind = 'directional' | 'ambient';

interface PlannedPulse {
  index: number;
  id: string;
  kind: PulseKind;
}

/** Directional signals take priority; calm structural flow fills the cap. */
export function planPulseLinks(links: RenderLink[]): PlannedPulse[] {
  const candidates = links.map((link, index) => ({
    index,
    id: String(link.id),
    kind: link.directed
      ? 'directional' as const
      : link.relationshipType.startsWith('domain:')
        ? 'ambient' as const
        : null,
  }));
  const byStableId = (a: typeof candidates[number], b: typeof candidates[number]) => (
    a.id < b.id ? -1 : a.id > b.id ? 1 : a.index - b.index
  );
  const directional = candidates
    .filter((candidate): candidate is typeof candidate & { kind: 'directional' } => candidate.kind === 'directional')
    .sort(byStableId)
    .slice(0, MAX_LIVE_PULSES);
  const remaining = MAX_LIVE_PULSES - directional.length;
  const ambient = candidates
    .filter((candidate): candidate is typeof candidate & { kind: 'ambient' } => candidate.kind === 'ambient')
    .sort(byStableId)
    .slice(0, remaining);
  return [...directional, ...ambient];
}

/** Deterministic top-K entity labels within each semantic data domain. */
export function topEntityLabelIds(layout: MobiusNode[], perDomain = 3): Set<string> {
  const domains = new Map<string, Array<{ id: string; val: number; order: number }>>();
  layout.forEach(({ node }, order) => {
    if (node.type === 'customer' || node.type === 'domain' || node.type === 'group' || node.type === 'empty') return;
    const list = domains.get(node.category) ?? [];
    list.push({
      id: node.id,
      val: Number.isFinite(node.val) ? node.val : Number.NEGATIVE_INFINITY,
      order,
    });
    domains.set(node.category, list);
  });
  const ids = new Set<string>();
  domains.forEach((nodes) => {
    nodes
      .sort((a, b) => b.val - a.val || a.order - b.order)
      .slice(0, perDomain)
      .forEach(({ id }) => ids.add(id));
  });
  return ids;
}

/**
 * Indexes of the links the canvas draws. When an entity belongs to a portion
 * group present in the projection, its hub -> entity trunk is redundant with
 * the hub -> group -> entity hierarchy, so only the hierarchy is drawn (the
 * doubled tubes saturated the additive glow into a white tangle). Every link
 * still counts for adjacency / hover / selection.
 */
export function drawnLinkIndexes(graph: RenderGraph): Set<number> {
  const groups = new Set(graph.nodes.filter((n) => n.type === 'group').map((n) => n.id));
  const groupedEntities = new Set(
    graph.nodes.filter((n) => typeof n.parentId === 'string' && groups.has(n.parentId)).map((n) => n.id),
  );
  const out = new Set<number>();
  graph.links.forEach((l, i) => {
    const s = String(l.source);
    const t = String(l.target);
    const hubTrunk = l.relationshipType.startsWith('domain:') && s.endsWith('-domain');
    if (hubTrunk && groupedEntities.has(t)) return;
    out.add(i);
  });
  return out;
}

export const EMPTY_SECTOR_PREFIX = 'sector-empty-';

/** One faint note per data-domain sector that has no data for this account. */
export function emptySectorNotes(present: Set<string>): Array<{ id: string; text: string; pos3: Vec3 }> {
  return DATA_DOMAIN_ORDER.filter((key) => !present.has(key)).map((key) => ({
    id: `${EMPTY_SECTOR_PREFIX}${key}`,
    text: `${CATEGORY_STYLES[key].label} · none`,
    pos3: networkPoint(domainU(key) ?? 0, 0),
  }));
}

/** Distribute domains and records through a dimensional network. */
export function networkPoint(u: number, v: number): Vec3 {
  const radius = 2.6 + v * 0.8;
  return [radius * Math.cos(u), Math.sin(u * 2) * 0.65 + v * 0.8, radius * Math.sin(u)];
}

export function isNodeInferred(node: MobiusNode['node']): boolean {
  return node.verified === false;
}

function createGlowTexture(): THREE.CanvasTexture | null {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.4, 'rgba(255,255,255,0.45)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

function geometryFor(shape: string, radius: number): THREE.BufferGeometry {
  if (shape === 'triangle') return new THREE.TetrahedronGeometry(radius * 1.35);
  if (shape === 'diamond') return new THREE.OctahedronGeometry(radius * 1.3);
  return new THREE.SphereGeometry(radius, 20, 20);
}

interface NodeEntry {
  id: string;
  mesh: THREE.Mesh;
  halo: THREE.Sprite;
  inferredEdges: THREE.LineSegments | null;
  baseMeshOpacity: number;
  baseEdgeOpacity: number;
  baseHaloOpacity: number;
  baseLabelOpacity: number;
  isCore: boolean;
}
interface TubeEntry {
  mesh: THREE.Mesh;
  source: string;
  target: string;
  baseOpacity: number;
  confidenceOpacity: number;
}
interface PulseEntry {
  curve: THREE.CatmullRomCurve3;
  mesh: THREE.Mesh;
  speed: number;
  offset: number;
  source: string;
  target: string;
}

export const MobiusGraphCanvas = forwardRef<MobiusCanvasHandle, Props>(
  function MobiusGraphCanvas(
    { graph, visibleIds, hoveredId, selectedId, reducedMotion, onHover, onSelect, onUnavailable },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const labelRefs = useRef<Record<string, HTMLDivElement | null>>({});
    const visibleLabelIdsRef = useRef<Set<string>>(new Set());
    const sceneRef = useRef<{ nodes: NodeEntry[]; tubes: TubeEntry[]; pulses: PulseEntry[] } | null>(null);
    const viewRef = useRef({ ...DEFAULT_VIEW });
    const cameraUpdateRef = useRef<() => void>(() => {});
    const reducedRef = useRef(reducedMotion);
    const hoveredRef = useRef<string | null>(null);
    const visibleRef = useRef(visibleIds);
    const callbacks = useRef({ onHover, onSelect, onUnavailable });
    callbacks.current = { onHover, onSelect, onUnavailable };

    const layout = useMemo<MobiusNode[]>(() => buildMobiusLayout(graph).map((entry) => ({ ...entry, pos3: entry.node.type === 'customer' ? entry.pos3 : networkPoint(entry.u, entry.v) })), [graph]);
    const byId = useMemo(() => {
      const m = new Map<string, MobiusNode>();
      layout.forEach((n) => m.set(n.node.id, n));
      return m;
    }, [layout]);
    const adjacency = useMemo(() => {
      const m = new Map<string, Set<string>>();
      graph.links.forEach((l) => {
        const s = String(l.source);
        const t = String(l.target);
        if (!m.has(s)) m.set(s, new Set());
        if (!m.has(t)) m.set(t, new Set());
        m.get(s)!.add(t);
        m.get(t)!.add(s);
      });
      return m;
    }, [graph]);
    // Data domains present in this projection (a hub exists) and how many
    // records each shows — read by the strip tint, the hub labels and the
    // empty-sector notes.
    const domainSummary = useMemo(() => {
      const present = new Set<string>();
      const counts = new Map<string, number>();
      graph.nodes.forEach((node) => {
        if (node.type === 'domain') present.add(node.category);
        else if (node.type !== 'customer' && node.type !== 'group' && node.type !== 'empty') {
          counts.set(node.category, (counts.get(node.category) ?? 0) + 1);
        }
      });
      return { present, counts };
    }, [graph]);
    const presentDomains = domainSummary.present;
    /** Sectors with no data for this account: a faint note, not an unexplained gap. */
    const emptySectors = useMemo(() => emptySectorNotes(presentDomains), [presentDomains]);
    const restingEntityLabelIds = useMemo(() => topEntityLabelIds(layout), [layout]);
    const visibleLabelIds = useMemo(() => {
      const ids = new Set<string>();
      const focusId = selectedId ?? hoveredId;
      const connected = focusId ? adjacency.get(focusId) : undefined;
      layout.forEach(({ node }) => {
        if (!visibleIds.has(node.id)) return;
        const structural = node.type === 'customer' || node.type === 'domain' || node.type === 'empty';
        if (structural || restingEntityLabelIds.has(node.id) || node.id === focusId || connected?.has(node.id)) {
          ids.add(node.id);
        }
      });
      return ids;
    }, [adjacency, hoveredId, layout, restingEntityLabelIds, selectedId, visibleIds]);
    visibleLabelIdsRef.current = visibleLabelIds;
    // Label placement order for the per-frame collision pass: the focused
    // node, the account, the focus neighbourhood, domain hubs, the
    // empty-sector notes (a sector-level fact outranks one entity label),
    // entities by importance, then empty-portion rings.
    const labelOrder = useMemo(() => {
      const focusId = selectedId ?? hoveredId;
      const connected = focusId ? adjacency.get(focusId) : undefined;
      const rank = ({ node }: MobiusNode): number => {
        if (node.id === focusId) return 0;
        if (node.type === 'customer') return 1;
        if (connected?.has(node.id)) return 2;
        if (node.type === 'domain') return 3;
        if (node.type === 'empty') return 6;
        return 4;
      };
      const ordered = [
        ...layout.map((entry, order) => ({ id: entry.node.id, r: rank(entry), val: Number.isFinite(entry.node.val) ? entry.node.val : 0, order })),
        ...emptySectors.map((e, i) => ({ id: e.id, r: 3.5, val: 0, order: layout.length + i })),
      ];
      return ordered.sort((a, b) => a.r - b.r || b.val - a.val || a.order - b.order).map((x) => x.id);
    }, [adjacency, emptySectors, hoveredId, layout, selectedId]);
    const labelOrderRef = useRef<string[]>(labelOrder);
    labelOrderRef.current = labelOrder;

    useImperativeHandle(ref, () => ({
      resetView: () => {
        Object.assign(viewRef.current, DEFAULT_VIEW);
        cameraUpdateRef.current();
      },
    }), []);

    useEffect(() => {
      reducedRef.current = reducedMotion;
    }, [reducedMotion]);
    visibleRef.current = visibleIds;

    // ---- mount the three.js scene once per projection ----
    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      let renderer: THREE.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true });
      } catch (err) {
        console.error(MOBIUS_WEBGL_MARKER, err);
        callbacks.current.onUnavailable();
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      const dom = renderer.domElement;
      container.appendChild(dom);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(MOBIUS_SURFACE.ink);
      const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);

      scene.add(new THREE.AmbientLight(0x30364a, 1.1));
      scene.add(new THREE.HemisphereLight(0xdbe4ff, 0x1a1030, 0.9));
      const light1 = new THREE.PointLight(0xf6d98c, 1.1, 40);
      light1.position.set(6, 4, 4);
      const light2 = new THREE.PointLight(0x4fb8d6, 0.9, 40);
      light2.position.set(-6, -3, -4);
      scene.add(light1, light2);

      // Backdrop stars: created once at mount (backdrop only; node placement
      // never uses randomness). Static — they never animate.
      const starCount = 500;
      const starPos = new Float32Array(starCount * 3);
      for (let i = 0; i < starCount; i++) {
        const r = 14 + Math.random() * 16;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        starPos[i * 3 + 1] = r * Math.cos(phi);
        starPos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
      }
      const starGeo = new THREE.BufferGeometry();
      starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
      scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 0.05, transparent: true, opacity: 0.5 })));

      const glowTexture = createGlowTexture();

      // nodes
      const nodeGroup = new THREE.Group();
      scene.add(nodeGroup);
      const nodes: NodeEntry[] = [];
      layout.forEach(({ node, pos3, radius }) => {
        const isCore = node.type === 'customer';
        const isGroup = node.type === 'group';
        const isEmpty = node.type === 'empty';
        const hierarchy = isGroup || isEmpty;
        const inferred = node.type !== 'customer' && node.type !== 'domain' && !hierarchy && isNodeInferred(node);
        const color = isCore ? MOBIUS_SURFACE.coreNode : mobiusColor(node.category);
        const shape = node.type === 'domain' || isCore || hierarchy ? 'circle' : styleFor(node.category).shape;
        // Drawn size is smaller than the layout's spacing radius so neighbours
        // keep visible air between them (placement itself is unchanged).
        const drawRadius = isCore ? 0.24 : node.type === 'domain' ? radius * 0.85 : radius * 0.72;
        const geometry = geometryFor(shape, drawRadius);
        const baseMeshOpacity = isEmpty ? 0.35 : isGroup ? 0.75 : inferred ? 0.6 : 1;
        // Lit, self-illuminated solids: they read as glossy 3D beads rather
        // than flat discs, while the emissive term keeps the category hue
        // luminous on the dark stage.
        const mesh = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: isCore ? 0.38 : 0.32,
            roughness: 0.38, metalness: 0.12, transparent: true, opacity: baseMeshOpacity,
          }),
        );
        const inferredEdges = inferred || isEmpty
          ? new THREE.LineSegments(
            new THREE.EdgesGeometry(geometry),
            new THREE.LineBasicMaterial({ color, transparent: true, opacity: isEmpty ? 0.5 : 0.78 }),
          )
          : null;
        if (inferredEdges) mesh.add(inferredEdges);
        mesh.position.set(pos3[0], pos3[1], pos3[2]);
        mesh.userData.id = node.id;
        nodeGroup.add(mesh);

        // Tight halos: a soft glow that marks the node without swallowing
        // its neighbours (the previous 5x halos merged into blobs).
        const haloScale = drawRadius * (isCore ? 5.5 : node.type === 'domain' ? 4 : hierarchy ? 3.4 : 3.8) * (inferred ? 0.8 : 1);
        const normalHaloOpacity = isCore ? 0.45 : node.type === 'domain' ? 0.32 : isEmpty ? 0.06 : isGroup ? 0.12 : 0.2;
        const baseHaloOpacity = inferred ? normalHaloOpacity * 0.5 : normalHaloOpacity;
        const haloColor = isCore ? MOBIUS_SURFACE.coreGlow : color;
        const halo = new THREE.Sprite(new THREE.SpriteMaterial({
          map: glowTexture, color: haloColor, transparent: true, opacity: baseHaloOpacity, depthWrite: false, blending: THREE.AdditiveBlending,
        }));
        halo.scale.set(haloScale, haloScale, 1);
        halo.position.copy(mesh.position);
        nodeGroup.add(halo);
        nodes.push({
          id: node.id,
          mesh,
          halo,
          inferredEdges,
          baseMeshOpacity,
          baseEdgeOpacity: isEmpty ? 0.5 : 0.78,
          baseHaloOpacity,
          baseLabelOpacity: node.type === 'customer' || node.type === 'domain' ? 0.92 : isEmpty ? 0.6 : 0.95,
          isCore,
        });
      });
      const pickables = nodes.map((n) => n.mesh);
      // Label anchors: node meshes + the empty-sector notes (not pickable).
      // `depthFloor`: the least a far-side label fades to (sector notes stay
      // legible from behind — they describe the whole sector).
      const anchors = new Map<string, { pos: THREE.Vector3; base: number; depthFloor: number }>();
      nodes.forEach((n) => anchors.set(n.id, { pos: n.mesh.position, base: n.baseLabelOpacity, depthFloor: 0.25 }));
      emptySectors.forEach((e) => anchors.set(e.id, { pos: new THREE.Vector3(...e.pos3), base: 0.7, depthFloor: 0.75 }));

      // links + pulses
      const tubeGroup = new THREE.Group();
      const pulseGroup = new THREE.Group();
      scene.add(tubeGroup, pulseGroup);
      const tubes: TubeEntry[] = [];
      const pulses: PulseEntry[] = [];
      const pulsePlan = new Map(planPulseLinks(graph.links).map((pulse) => [pulse.index, pulse.kind]));
      const drawn = drawnLinkIndexes(graph);
      graph.links.forEach((l, i) => {
        const s = String(l.source);
        const t = String(l.target);
        const a = byId.get(s);
        const b = byId.get(t);
        if (!a || !b || !drawn.has(i)) return;
        // Cross-domain links receive a brighter visual treatment.
        const cross = isCrossDomainLink(a, b, l.relationshipType);
        // The account connects to domain hubs with gently curved spokes.
        const spokeTo: Vec3 | null = a.node.type === 'customer' ? b.pos3 : b.node.type === 'customer' ? a.pos3 : null;
        const raw = spokeTo ? buildSpokePoints(spokeTo) : [a.pos3, b.pos3];
        const pts = (spokeTo && a.node.type !== 'customer' ? [...raw].reverse() : raw).map((p) => new THREE.Vector3(p[0], p[1], p[2]));
        const curve = new THREE.CatmullRomCurve3(pts);
        const isTrunk = l.relationshipType.startsWith('domain:');
        // hue: the entity endpoint's domain, else the hub's domain
        const entity = a.node.type !== 'customer' && a.node.type !== 'domain' ? a.node
          : b.node.type !== 'customer' && b.node.type !== 'domain' ? b.node
          : a.node.type === 'domain' ? a.node : b.node;
        const color = mobiusColor(entity.category);
        const inferredLink = isNodeInferred(a.node) || isNodeInferred(b.node);
        const confidenceOpacity = inferredLink ? 0.6 : 1;
        const isSpoke = spokeTo !== null;
        const structural = l.relationshipType.startsWith('supports:') || l.relationshipType.startsWith('portion:');
        const baseOpacity = (isSpoke ? 0.5 : isTrunk ? 0.36 : structural ? 0.2 : cross ? 0.55 : 0.3) * confidenceOpacity;

        const mesh = new THREE.Mesh(
          new THREE.TubeGeometry(curve, 48, isSpoke ? 0.022 : isTrunk ? 0.016 : cross ? 0.016 : 0.011, 6, false),
          new THREE.MeshBasicMaterial({ color, transparent: true, opacity: baseOpacity, blending: THREE.AdditiveBlending, depthWrite: false }),
        );
        tubeGroup.add(mesh);
        tubes.push({ mesh, source: s, target: t, baseOpacity, confidenceOpacity });

        const pulseKind = pulsePlan.get(i);
        if (pulseKind) {
          const directional = pulseKind === 'directional';
          const pulse = new THREE.Mesh(
            new THREE.SphereGeometry(directional ? 0.035 : 0.022, 8, 8),
            new THREE.MeshBasicMaterial({ color, transparent: true, opacity: (directional ? 0.95 : 0.34) * confidenceOpacity }),
          );
          const pulseHalo = new THREE.Sprite(new THREE.SpriteMaterial({
            map: glowTexture, color, transparent: true, opacity: (directional ? 0.55 : 0.18) * confidenceOpacity, depthWrite: false, blending: THREE.AdditiveBlending,
          }));
          const pulseHaloScale = directional ? 0.5 : 0.3;
          pulseHalo.scale.set(pulseHaloScale, pulseHaloScale, 1);
          pulse.add(pulseHalo);
          pulse.visible = false;
          pulseGroup.add(pulse);
          pulses.push({
            curve, mesh: pulse, source: s, target: t,
            speed: directional
              ? 0.09 + ((i * 13) % 5) * 0.025
              : 0.025 + ((i * 7) % 4) * 0.006,
            offset: ((i * 29) % 10) / 10,
          });
        }
      });
      sceneRef.current = { nodes, tubes, pulses };

      // camera orbit
      const view = viewRef.current;
      let autoRotate = !reducedRef.current;
      let resumeTimer: ReturnType<typeof setTimeout> | null = null;
      const updateCamera = () => {
        const { azimuth, elevation, radius } = view;
        camera.position.set(
          radius * Math.sin(azimuth) * Math.cos(elevation),
          radius * Math.sin(elevation),
          radius * Math.cos(azimuth) * Math.cos(elevation),
        );
        camera.lookAt(0, 0, 0);
      };
      cameraUpdateRef.current = updateCamera;
      updateCamera();

      const raycaster = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      let dragging = false;
      let dragged = false;
      let last = { x: 0, y: 0 };
      const pickId = (): string | null => {
        raycaster.setFromCamera(ndc, camera);
        const hits = raycaster
          .intersectObjects(pickables)
          .filter((h) => visibleRef.current.has(h.object.userData.id));
        return hits.length ? (hits[0].object.userData.id as string) : null;
      };
      const setNdc = (e: PointerEvent) => {
        const rect = dom.getBoundingClientRect();
        ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      };
      const scheduleResume = () => {
        if (resumeTimer) clearTimeout(resumeTimer);
        resumeTimer = setTimeout(() => { autoRotate = true; }, 2200);
      };
      const onPointerDown = (e: PointerEvent) => {
        dragging = true;
        dragged = false;
        autoRotate = false;
        if (resumeTimer) clearTimeout(resumeTimer);
        last = { x: e.clientX, y: e.clientY };
      };
      const onPointerMove = (e: PointerEvent) => {
        setNdc(e);
        if (dragging) {
          const dx = e.clientX - last.x;
          const dy = e.clientY - last.y;
          if (Math.abs(dx) + Math.abs(dy) > 2) dragged = true;
          view.azimuth -= dx * 0.006;
          view.elevation = Math.min(1.4, Math.max(0.1, view.elevation + dy * 0.006));
          last = { x: e.clientX, y: e.clientY };
          updateCamera();
        } else {
          const id = pickId();
          if (id !== hoveredRef.current) {
            hoveredRef.current = id;
            callbacks.current.onHover(id);
          }
        }
      };
      const onPointerUp = () => {
        if (!dragging) return;
        dragging = false;
        if (!dragged) callbacks.current.onSelect(pickId());
        scheduleResume();
      };
      const onWheel = (e: WheelEvent) => {
        e.preventDefault();
        view.radius = Math.min(13, Math.max(4.5, view.radius + e.deltaY * 0.004));
        updateCamera();
      };
      const onContextLost = (e: Event) => {
        e.preventDefault();
        console.error(MOBIUS_WEBGL_MARKER, 'context lost');
        callbacks.current.onUnavailable();
      };
      dom.style.touchAction = 'none';
      dom.style.cursor = 'grab';
      dom.addEventListener('pointerdown', onPointerDown);
      dom.addEventListener('wheel', onWheel, { passive: false });
      dom.addEventListener('webglcontextlost', onContextLost);
      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp);

      const resize = () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (w === 0 || h === 0) return;
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      resize();
      const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
      ro?.observe(container);

      const tmp = new THREE.Vector3();
      const cameraSpace = new THREE.Vector3();
      const clock = new THREE.Clock();
      let raf = 0;
      let failed = false;
      const animate = () => {
        raf = requestAnimationFrame(animate);
        const dt = Math.min(clock.getDelta(), 0.05);
        const elapsed = clock.getElapsedTime();
        const reduced = reducedRef.current;

        if (autoRotate && !dragging && !reduced) {
          view.azimuth += dt * 0.06;
          updateCamera();
        }
        pulses.forEach((p) => {
          if (reduced) { p.mesh.visible = false; return; }
          p.mesh.visible = visibleRef.current.has(p.source) && visibleRef.current.has(p.target);
          p.curve.getPointAt((elapsed * p.speed + p.offset) % 1, p.mesh.position);
        });
        nodes.forEach((n) => {
          if (n.isCore) {
            const breathe = reduced ? 1.3 : 1.3 * (1 + Math.sin(elapsed * 1.5) * 0.1);
            n.halo.scale.set(breathe, breathe, 1);
          }
        });

        const w = container.clientWidth;
        const h = container.clientHeight;
        // Greedy collision pass in priority order: a label that would overlap
        // one already placed this frame is hidden (it returns when the view
        // rotates or the node is focused).
        const placed: Array<[number, number, number, number]> = [];
        labelOrderRef.current.forEach((id) => {
          const el = labelRefs.current[id];
          const anchor = anchors.get(id);
          if (!el || !anchor) return;
          const hide = () => {
            el.style.opacity = '0';
            el.style.transform = 'translate(-9999px,-9999px)';
          };
          tmp.copy(anchor.pos).project(camera);
          const shown = id.startsWith(EMPTY_SECTOR_PREFIX) || visibleLabelIdsRef.current.has(id);
          if (tmp.z > 1 || tmp.z < -1 || !shown) { hide(); return; }
          const x = (tmp.x * 0.5 + 0.5) * w + 10;
          const y = (-tmp.y * 0.5 + 0.5) * h - 6;
          const lw = el.offsetWidth;
          const lh = el.offsetHeight;
          if (lw > 0 && placed.some(([px, py, pw, ph]) => x < px + pw + 3 && px < x + lw + 3 && y < py + ph + 2 && py < y + lh + 2)) {
            hide();
            return;
          }
          placed.push([x, y, lw, lh]);
          cameraSpace.copy(anchor.pos).applyMatrix4(camera.matrixWorldInverse);
          const depthOpacity = -cameraSpace.z > camera.position.length() ? anchor.depthFloor : 1;
          el.style.opacity = String(anchor.base * depthOpacity);
          el.style.transform = `translate(${x}px, ${y}px)`;
        });

        try {
          renderer.render(scene, camera);
        } catch (err) {
          if (!failed) {
            failed = true;
            cancelAnimationFrame(raf);
            console.error(MOBIUS_WEBGL_MARKER, err);
            callbacks.current.onUnavailable();
          }
        }
      };
      animate();

      return () => {
        cancelAnimationFrame(raf);
        if (resumeTimer) clearTimeout(resumeTimer);
        ro?.disconnect();
        dom.removeEventListener('pointerdown', onPointerDown);
        dom.removeEventListener('wheel', onWheel);
        dom.removeEventListener('webglcontextlost', onContextLost);
        window.removeEventListener('pointermove', onPointerMove);
        window.removeEventListener('pointerup', onPointerUp);
        if (dom.parentNode === container) container.removeChild(dom);
        scene.traverse((obj) => {
          const o = obj as THREE.Mesh;
          o.geometry?.dispose();
          const m = o.material as THREE.Material | THREE.Material[] | undefined;
          if (Array.isArray(m)) m.forEach((x) => x.dispose());
          else m?.dispose();
        });
        glowTexture?.dispose();
        renderer.dispose();
        sceneRef.current = null;
        cameraUpdateRef.current = () => {};
      };
    }, [layout, byId, graph, presentDomains, emptySectors]);

    // ---- hover / selection / filter sync (no scene rebuild) ----
    useEffect(() => {
      const s = sceneRef.current;
      if (!s) return;
      const focusId = selectedId ?? hoveredId;
      const connected = focusId ? adjacency.get(focusId) : undefined;
      s.nodes.forEach(({ id, mesh, halo, inferredEdges, baseMeshOpacity, baseHaloOpacity, baseEdgeOpacity }) => {
        const visible = visibleIds.has(id);
        mesh.visible = visible;
        halo.visible = visible;
        const dim = focusId && id !== focusId && !(connected && connected.has(id));
        (mesh.material as THREE.MeshStandardMaterial).opacity = dim ? 0.18 : baseMeshOpacity;
        (halo.material as THREE.SpriteMaterial).opacity = dim ? 0.06 : baseHaloOpacity;
        if (inferredEdges) {
          (inferredEdges.material as THREE.LineBasicMaterial).opacity = dim ? 0.12 : baseEdgeOpacity;
        }
      });
      s.tubes.forEach(({ mesh, source, target, baseOpacity, confidenceOpacity }) => {
        mesh.visible = visibleIds.has(source) && visibleIds.has(target);
        const active = focusId && (source === focusId || target === focusId);
        (mesh.material as THREE.MeshBasicMaterial).opacity = focusId && !active
          ? 0.06 * confidenceOpacity
          : active
            ? 0.9 * confidenceOpacity
            : baseOpacity;
      });
    }, [hoveredId, selectedId, visibleIds, adjacency, layout]);

    return (
      <div
        data-testid="mobius-graph-canvas"
        style={{ position: 'absolute', inset: 0, background: MOBIUS_SURFACE.ink }}
      >
        <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
        {layout.map(({ node }) => {
          const entity = node.type !== 'customer' && node.type !== 'domain';
          const shown = visibleLabelIds.has(node.id);
          const inferred = entity && node.type !== 'group' && node.type !== 'empty' && isNodeInferred(node);
          const hub = node.type === 'domain';
          const core = node.type === 'customer';
          const hue = mobiusColor(node.category);
          return (
            <div
              key={node.id}
              ref={(el) => { labelRefs.current[node.id] = el; }}
              aria-hidden
              style={{
                position: 'absolute', top: 0, left: 0, pointerEvents: 'none', userSelect: 'none', whiteSpace: 'nowrap',
                fontSize: core ? 14 : hub ? 12 : 11,
                fontWeight: entity ? 400 : 600,
                color: MOBIUS_SURFACE.textPrimary,
                background: 'rgba(5,8,16,0.72)',
                border: inferred ? '1px dashed rgba(231,236,245,0.48)' : '1px solid rgba(148,163,184,0.12)',
                borderLeft: hub ? `3px solid ${hue}` : core ? `3px solid ${MOBIUS_SURFACE.coreGlow}` : undefined,
                borderRadius: 5,
                padding: core ? '3px 8px' : '2px 5px',
                opacity: shown ? (entity ? 0.95 : 0.92) : 0,
                transition: 'opacity 0.15s ease',
              }}
            >
              {node.label}
              {hub && (
                <span style={{ marginLeft: 6, fontWeight: 500, color: MOBIUS_SURFACE.textMuted }}>
                  {domainSummary.counts.get(node.category) ?? 0}
                </span>
              )}
            </div>
          );
        })}
        {emptySectors.map((sector) => (
          <div
            key={sector.id}
            ref={(el) => { labelRefs.current[sector.id] = el; }}
            aria-hidden
            data-testid={sector.id}
            style={{
              position: 'absolute', top: 0, left: 0, pointerEvents: 'none', userSelect: 'none', whiteSpace: 'nowrap',
              fontSize: 10.5, fontStyle: 'italic', color: MOBIUS_SURFACE.textMuted, opacity: 0,
              transition: 'opacity 0.15s ease',
            }}
          >
            {sector.text}
          </div>
        ))}
      </div>
    );
  },
);

export default MobiusGraphCanvas;
