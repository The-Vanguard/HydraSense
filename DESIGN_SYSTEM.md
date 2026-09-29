# Design System & Interface Style Guide

This document outlines the visual language, interface style, and design components used in the Disaster Management GIS Dashboard project. The design merges a **"Minimalist Cloud SaaS Theme"** (named *Cirrus*) with a **"Modern Enterprise Executive Theme"**.

## 1. Typography
The project relies on Google Fonts to establish a clean, modern, and highly legible typographic hierarchy.
- **Primary / Sans-Serif:** `Inter`, system-ui, -apple-system, BlinkMacSystemFont, sans-serif
  Used for standard text, buttons, and UI elements.
- **Display / Headings:** `Inter Tight`, `Inter`, system-ui, sans-serif
  Used for emphasized headers and titles to give a slightly tighter, punchier appearance.
- **Monospace:** `JetBrains Mono`, monospace
  Used for data points, coordinates, code snippets, or tabular data requiring vertical alignment.

## 2. Color Palette
The color scheme is designed to be professional, high-contrast, and intuitive for a data-dense executive dashboard.

### Core Colors
- **Ink (Primary Dark):** `#0e1116` (Hover: `#1a1f28`)
- **Cloud (Primary Light/Background):** `#ffffff`
- **Mist (Secondary Text/Icons):** `#5b6472`
- **Mist Light (Muted Text):** `#94a3b8`

### UI & Backgrounds
- **App Container Background (Light Mode):** `#f4f6fb` (with specific views using `#f7f6f0` like the dashboard and alerts)
- **App Container Background (Dark Mode):** `#0a0f1d` (Text: `#f3f4f6`)
- **Edge/Borders:** `#e3e8ee` (Subtle: `#edf2f7`)
- **Sky/Surface Backgrounds:** Subtle (`#f8fafc`), Tint (`#f0f6ff`), Accent (`#e0f2fe`)

### Brand & Interactive
- **Blue Accent (Primary Call-to-Action):** `#2e7def` (Hover: `#1d68db`)
- **Active Navigation Tab:** `#2563eb`

### Status & Semantic Colors
Critical for a disaster management dashboard to convey urgency and state:
- **Success / Safe:** Emerald (`#10b981`), Soft (`#ecfdf5`)
- **Warning / Medium Alert:** Amber (`#f59e0b`), Soft (`#fffbeb`) & Orange (`#f97316`), Soft (`#fff7ed`)
- **Critical / Danger:** Red (`#ef4444`), Soft (`#fef2f2`)

## 3. Shapes & Border Radius
The interface leans towards soft, approachable geometry mixed with sharp interior boundaries for data containment.
- **Pill (Buttons/Badges):** `999px` (Fully rounded ends)
- **Cards/Containers:** `22px` (Large, soft outer rounding)
- **Inner Elements:** `14px` (Slightly sharper to nest perfectly within cards)
- **Small UI Elements (Tabs, Inputs):** `8px` or `6px`

## 4. Shadows & Elevation
Shadows are used to establish a physical hierarchy and depth (glassmorphism and modern elevation).
- **Small (Hover states/Inputs):** `0 1px 2px rgba(14, 17, 22, 0.04)`
- **Card:** `0 1px 1px rgba(14, 17, 22, 0.04), 0 20px 40px -24px rgba(14, 17, 22, 0.18)`
- **Elevated (Modals/Popovers):** `0 1px 1px rgba(14, 17, 22, 0.06), 0 24px 48px -18px rgba(14, 17, 22, 0.22)`
- **Button:** `0 1px 1px rgba(14, 17, 22, 0.06), 0 14px 28px -18px rgba(14, 17, 22, 0.4)`

## 5. Components & Layout Style
- **Buttons (`.cir-btn`):** Pill-shaped, primarily using the "Ink" background with "Cloud" text, featuring a subtle shadow and smooth transformation on hover (`transform`, `background-color`, `box-shadow` transitions).
- **Navigation Tabs:** Glassmorphism effect with a semi-transparent dark background (`rgba(15, 23, 42, 0.75)`), subtle borders, and smooth hover states. Active tabs pop with a bright blue background and corresponding colored drop shadow.
- **Layout:** Flexbox-heavy, full-screen viewport (`100vw`, `100vh`) with hidden overflows on the main container, directing scroll behaviors to specific internal views (e.g., dashboard, alerts).
- **Scrollbars:** Styled thinly using `scrollbar-width: thin` to remain unobtrusive and maintain the sleek, modern aesthetic.

## Overall Vibe
The design feels very "Premium B2B/SaaS". It avoids stark, plain colors by utilizing soft grays ("Mist"), subtle tinted backgrounds, highly considered typographic pairings (Inter & JetBrains Mono), and deep, layered shadows to give cards a floating, tactile feel.
