import type { ReactNode } from 'react';

export type IconName =
    | 'alert'
    | 'bell'
    | 'book'
    | 'brain'
    | 'calendar'
    | 'check'
    | 'chevron'
    | 'chevron-left'
    | 'clock'
    | 'close'
    | 'close-circle'
    | 'database'
    | 'download'
    | 'expand'
    | 'external'
    | 'file'
    | 'filter'
    | 'flask'
    | 'folder'
    | 'gauge'
    | 'gavel'
    | 'globe'
    | 'home'
    | 'info'
    | 'layers'
    | 'link'
    | 'loop'
    | 'menu'
    | 'more'
    | 'nodes'
    | 'pause'
    | 'play'
    | 'play-circle'
    | 'pulse'
    | 'reset'
    | 'search'
    | 'settings'
    | 'shield'
    | 'sliders'
    | 'stop'
    | 'target'
    | 'trend'
    | 'users'
    | 'wave';

const PATHS: Record<IconName, ReactNode> = {
    alert: <path d="M12 3 2.5 20h19L12 3Zm0 6v5m0 3h.01" />,
    bell: <path d="M18 16v-5a6 6 0 0 0-12 0v5l-2 3h16l-2-3Zm-8 6h4" />,
    book: <path d="M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 0-4 4V4Zm4 0v16" />,
    brain: <path d="M8 6a4 4 0 0 0-1 7 4 4 0 0 0 3 7h1V4H9a4 4 0 0 0-1 2Zm5-2v16h1a4 4 0 0 0 3-7 4 4 0 0 0-1-7 4 4 0 0 0-3-2Z" />,
    calendar: <path d="M5 5h14v15H5V5Zm3-3v5m8-5v5M5 10h14" />,
    check: <path d="m4 12 5 5L20 6" />,
    chevron: <path d="m9 6 6 6-6 6" />,
    'chevron-left': <path d="m15 18-6-6 6-6" />,
    clock: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v5l3 2" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    'close-circle': <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-3-6 6-6m0 6L9 9" />,
    database: <path d="M4 7c0-2 16-2 16 0v10c0 2-16 2-16 0V7Zm0 5c0 2 16 2 16 0M4 17c0 2 16 2 16 0" />,
    download: <path d="M12 3v12m-5-5 5 5 5-5M5 21h14" />,
    expand: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" />,
    external: <path d="M14 4h6v6m0-6-9 9M20 14v6H4V4h6" />,
    file: <path d="M6 3h9l4 4v14H6V3Zm8 0v5h5M9 13h6m-6 4h6" />,
    filter: <path d="M4 5h16l-6 7v6l-4 2v-8L4 5Z" />,
    flask: <path d="M9 3h6m-5 0v6l-5 9a3 3 0 0 0 3 4h8a3 3 0 0 0 3-4l-5-9V3" />,
    folder: <path d="M3 6h7l2 3h9v10H3V6Z" />,
    gauge: <path d="M4 15a8 8 0 1 1 16 0M12 15l5-5" />,
    gavel: <path d="m14 5 5 5-3 3-5-5 3-3Zm-2 5-6 6m12 3H8" />,
    globe: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-8-9h16M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" />,
    home: <path d="m3 11 9-8 9 8v10h-6v-6H9v6H3V11Z" />,
    info: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v6m0-9h.01" />,
    layers: <path d="m12 3 9 5-9 5-9-5 9-5Zm-7 9 7 4 7-4M5 16l7 4 7-4" />,
    link: <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />,
    loop: <path d="M4 12a8 8 0 0 1 13-6l2 2m1 4a8 8 0 0 1-13 6l-2-2M17 6h2V4M7 18H5v2" />,
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    more: <path d="M12 6h.01M12 12h.01M12 18h.01" />,
    nodes: <path d="M12 3v6m0 0-6 5m6-5 6 5M6 14v7m12-7v7M12 9v12M4 21h4m8 0h4m-6 0h-4" />,
    pause: <path d="M8 5h3v14H8V5Zm5 0h3v14h-3V5Z" />,
    play: <path d="m8 5 11 7-11 7V5Z" />,
    'play-circle': <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-3-13 7 4-7 4V8Z" />,
    pulse: <path d="M3 12h4l2-6 4 12 2-6h6" />,
    reset: <path d="M20 12a8 8 0 1 1-2.3-5.7L20 8m0-5v5h-5" />,
    search: <path d="M11 19a8 8 0 1 1 5.7-2.3L21 21" />,
    settings: <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm0-12v3m0 11v3m8.5-8.5h-3m-11 0h-3m14.4-6.4-2.1 2.1M8.2 15.8 6.1 17.9m11.8 0-2.1-2.1M8.2 8.2 6.1 6.1" />,
    shield: <path d="M12 3 20 6v6c0 5-3.2 8.2-8 10-4.8-1.8-8-5-8-10V6l8-3Zm-4 9 3 3 5-6" />,
    sliders: <path d="M4 7h7m4 0h5M4 12h12m-9 5h13M11 5v4m5 1v4M7 15v4" />,
    stop: <path d="M7 7h10v10H7V7Z" />,
    target: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-3a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" />,
    trend: <path d="M4 18 9 13l4 3 7-10m0 0v6m0-6h-6" />,
    users: <path d="M16 21v-2a4 4 0 0 0-8 0v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm8 10v-2a3 3 0 0 0-3-3m1-12a3 3 0 0 1 0 6" />,
    wave: <path d="M3 12c3-6 6 6 9 0s6 6 9 0" />,
};

export function Icon({ name }: { name: IconName }) {
    return (
        <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
            {PATHS[name]}
        </svg>
    );
}

export function BrandMark() {
    return (
        <svg className="brand-mark" viewBox="0 0 40 40" aria-hidden="true">
            <path d="M20 3 33 8v9c0 8.7-5.1 15.2-13 19-7.9-3.8-13-10.3-13-19V8l13-5Z" />
            <path d="m13 20 4.5 4.5L28 13.5" />
            <path d="M11 11 20 7l9 4" />
        </svg>
    );
}

export function iconForAgent(name: string): IconName {
    if (name.includes('RedTeam')) return 'target';
    if (name.includes('Simulator')) return 'trend';
    if (name.includes('Risk')) return 'shield';
    if (name.includes('Investigator')) return 'search';
    if (name.includes('Policy')) return 'gavel';
    if (name.includes('Memory')) return 'database';
    if (name.includes('Trainer')) return 'nodes';
    return 'settings';
}
