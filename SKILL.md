---
name: qronos-system-design
description: Complete design system for the Qronos-style dark tech landing page (stateful runtime for AI agents). Use when building or cloning dark-themed SaaS/tech landing pages with hairline frames, corner ticks, gradient text, light-sweep buttons, logo marquees, section dividers, sidebar/Gantt mockups, dithering or particle backgrounds, or when applying Qronos colors, tokens, spacing, borders and motion to any new project or page. Triggers on "Qronos design", "sistema de diseño de Qronos", "clonar esta estética", "dark landing", "hairlines", "esquinas con ticks", "botón con luz en el borde", "marquee de logos", "divisor de secciones", "mockups estilo runtime".
---

# Qronos System Design — Guía de diseño de la landing

Sistema de diseño extraído de la landing "Qronos" (gestión de scheduling para agentes autónomos). Aplícalo para replicar la estética en otras páginas o proyectos nuevos: colores, tipografía, marcos, decoraciones, animaciones y componentes.

Principio rector: **superficies oscuras casi negras + marcos con hairlines luminosos + acentos violeta/teal + tipografía grande y apretada**. Nada de sombras difusas de colores; la profundidad se logra con bordes finos, degradados sutiles de 145° y resaltes internos de 1px.

## Quick Reference

| Categoría | Aplicar cuando… |
| --- | --- |
| [Tokens y colores](#tokens-y-colores) | Definir CSS vars, paleta, gradientes de texto |
| [Tipografía](#tipografia) | Encabezados de sección, dos líneas (blanco + gris), títulos de hero |
| [Layout y espaciado](#layout-y-espaciado) | Contenedores 1344/1400px, grid de encabezados 7/5, paddings de sección |
| [Marcos y paneles](#marcos-y-paneles) | Tarjetas, mockups, frames con hairline y ticks de esquina |
| [Decoraciones](#decoraciones) | Divisores de sección, rails laterales, hairlines sueltos |
| [Botones](#botones) | StarButton con luz en el borde, pill blanca con hairline |
| [Fondos](#fondos) | Partículas (iframe), dithering B/N, glow violeta + rejilla |
| [Animaciones](#animaciones) | Keyframes (luz, marquee, barrido), transiciones, reduced-motion |
| [Mockups](#mockups) | Sidebar+Gantt, pipeline animado, schedule, guardrails, inbox |

## Tokens y colores

Definir en CSS (`@theme` de Tailwind v4 o `:root`):

```css
--color-ink: #050507;            /* fondo de página */
--color-surface: #0b0b10;
--color-surface-2: #101018;
--color-surface-3: #16161f;
--color-background: #050507;
--color-foreground: #fafafa;     /* texto principal */
--color-muted-foreground: #9b9ba8;
--color-muted: #9b9ba8;
--color-faint: #646472;
--color-line: rgba(255,255,255,0.08);
--color-line-strong: rgba(255,255,255,0.14);
--color-frame: #37333b;          /* borde de paneles */
--color-border: #26262b;         /* bordes de líneas decorativas exteriores */
--color-accent: #8b7bff;         /* violeta */
--color-accent-soft: rgba(139,123,255,0.14);
/* teal secundario: #5EEAD4 (usado en gradientes del logo y acentos) */
```

Reglas de uso:

1. **Fondo de página**: `bg-ink` (#050507), nunca negro puro salvo dentro de mockups (`#09090c`, `#0a0a0c`, `#101112`).
2. **Bordes estructurales**: `border-frame` (#37333b) para marcos de tarjetas; `border-line`/`border-line-strong` para separadores ligeros.
3. **Gradiente de superficie estándar de tarjetas**:
   `bg-[linear-gradient(145deg,rgba(19,19,21,0.98),rgba(7,7,8,0.98))]`
4. **Sombras internas de profundidad** (no usar box-shadow de elevación):
   - Marco exterior: `shadow-[inset_0_1px_0_rgba(255,255,255,0.08),inset_0_-1px_0_rgba(0,0,0,0.7)]`
   - Tarjeta interna: `shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]`
5. **Hairline luminoso** (línea de 1px que brilla al centro):
   `absolute left-4.5 top-0 h-px w-[calc(100%-2.25rem)] bg-linear-to-r from-slate-300/0 via-slate-200/90 to-slate-300/0`
   Variante con color oscuro (sobre botón blanco): `from-neutral-950/0 via-neutral-500 to-neutral-950/0`.
6. **Ticks de esquina** (cruces que marcan las 4 esquinas de un contenedor): `size-3`, con `before:` línea horizontal y `after:` línea vertical, ambas con gradiente
   `linear-gradient(to_right,transparent,rgba(226,232,240,0.65)_50%,transparent)` (y `to_bottom` para la vertical), o versión atenuada `bg-foreground/25` con máscara radial `mask-[radial-gradient(circle_at_center,_black_15%,_transparent_75%)]`.
7. **Gradiente de texto** (títulos y segunda línea del hero):
   `bg-linear-to-b from-white via-zinc-300 to-zinc-500 bg-clip-text text-transparent`

## Tipografía

- Familia: **Inter Variable** (`--font-sans` y `--font-display` apuntan a ella; `font-display` para títulos).
- Encabezado de sección estándar (2 líneas, la segunda en gris):
  - `font-display text-[37px] leading-[0.95] tracking-tight lg:text-[48px]`
  - Línea 1: `block text-foreground` · Línea 2: `mt-1 block text-muted-foreground lg:mt-3`
- Hero: `text-[clamp(2rem,9vw,2.5rem)] leading-[0.96] sm:text-[clamp(2rem,4.6vw,4.5rem)] sm:leading-[0.92]`, dividido en dos `<span class="block sm:whitespace-nowrap">`.
- Párrafo de soporte de sección: `text-xl leading-relaxed text-muted-foreground`.
- Texto de mockups: `font-mono` de 8–10px con `tracking-[0.06em..0.16em]` para etiquetas técnicas, `text-white/24..72` para jerarquías tenues.
- Icons (lucide): stroke `1.5` junto a texto regular; tamaño `size-4` dentro de chips `size-8`.

## Layout y espaciado

- **Dos anchos**: `max-w-336` (1344px) para nav, fondos y decoraciones; `max-w-350` (1400px) para el contenido, con `px-3.75 lg:px-14` (15px/56px).
- **Márgenes laterales en lg**: `calc(100%-3.5rem)` (28px por lado) en nav y fondos.
- **Paddings de sección**: `py-24 lg:py-32` (o `pt-24 pb-16 lg:pt-32 lg:pb-20` cuando hay decoración inferior).
- **Encabezado de sección**: `grid items-end gap-8 lg:grid-cols-12` con H2 en `lg:col-span-7` y párrafo en `lg:col-span-5 lg:pb-4`.
- **Grid de tarjetas**: `grid gap-8 lg:grid-cols-2 lg:gap-12` o `md:grid-cols-2` con el contenedor compartido (ver marcos).
- Anchors con `scroll-mt-24` por el header fijo.

## Marcos y paneles

1. **Marco exterior** (tarjeta grande / mockup):
   `relative overflow-hidden rounded-[14px] border border-frame bg-[linear-gradient(145deg,rgba(19,19,21,0.98),rgba(7,7,8,0.98))] p-1.25 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),inset_0_-1px_0_rgba(0,0,0,0.7)]`
2. **Tarjeta interna**: `rounded-lg border border-frame` + mismo gradiente + `shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]`. Radio concéntrico: exterior 14px → interior 8px (con padding 5px).
3. **Hairline superior (e inferior si aplica)** del marco: regla 5 de Tokens.
4. **Máscara de desvanecido inferior** para mockups que se funden con el texto:
   `mask-[linear-gradient(to_bottom,#000_0%,#000_76%,transparent_100%)]` (+ `[-webkit-mask-image:…]` equivalente).
5. **Panel oscuro interno de mockups**: `rounded-lg border border-white/8 bg-[#101112] shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]`.
6. **Tarjetas de testimonios**: marco + 4 líneas exteriores a -12px (`-top-3 -bottom-3 -left-3 -right-3`) con gradiente
   `linear-gradient(...,transparent_0%,_var(--color-border)_6.5%,_var(--color-border)_93.5%,_transparent_100%)` y 4 ticks de esquina (regla 6).
7. **Hover**: subrayado inferior con gradiente `h-px w-0 bg-linear-to-r from-slate-300/0 via-slate-200/90 to-slate-300/0 transition-all duration-500 group-hover:w-full`.

## Decoraciones

- **SectionDivider** (entre secciones): contenedor `relative mx-auto h-10 w-full max-w-336 lg:w-[calc(100%-3.5rem)]`; banda `absolute inset-x-0 top-1/2 h-10 -translate-y-1/2 border-y border-white/12 bg-[repeating-linear-gradient(135deg,transparent_0,transparent_6px,rgba(255,255,255,0.06)_6px,rgba(255,255,255,0.06)_7px)]` + 4 ticks de esquina.
- **SideRails** (líneas verticales decorativas): contenedor `pointer-events-none absolute inset-0 z-15 hidden md:block` dentro del wrapper `relative` de la página; cada rail anclado con `left-0 lg:left-[max(1.75rem,calc(50%-42rem))]` (y espejo `right-`); línea `w-px bg-white/12` de `top-20` a `bottom-0`; ticks horizontales con el gradiente de la regla 6 cada ~8%; logo cuadrado arriba (`top-24`); franja rayada `bottom-[10%] h-44 w-3 border-x border-white/12` con el mismo `repeating-linear-gradient(135deg…)` del divisor.
- Los divisores y rails van con `aria-hidden` y `pointer-events-none`.

## Botones

- **StarButton** (CTA principal, luz recorriendo el borde):
  - `<button>` con `border border-slate-200/50 rounded-full` (o `rounded-3xl` en nav) y `overflow-hidden isolate z-3`.
  - Luz: `<span class="animate-star-btn absolute inset-0 aspect-square w-27.5 bg-[radial-gradient(ellipse_at_center,var(--light-color),transparent,transparent)]">` con `offset-path: var(--path)`; vars CSS: `--light-color:#FAFAFA`, `--light-width:110px`, `--border-width:2px`.
  - Panel interior que deja ver solo el anillo: `absolute inset-0.5 z-4 overflow-hidden rounded-[inherit] border border-white/15 bg-black`.
  - Texto en `relative z-10 text-white`.
  - Paths por tamaño: `sm` `path('M 0 0 H 126 V 32 H 0 V 0')` (h-8), `hero` `path('M 0 0 H 142 V 40 H 0 V 0')` (h-10 px-5 rounded-full), `md` `path('M 0 0 H 248 V 40 H 0 V 0')`.
- **Pill blanca** (secundario): `relative isolate h-10 rounded-full border border-white/30 bg-white px-5 text-black` con hairline superior oscuro (`from-neutral-950/0 via-neutral-500 to-neutral-950/0`).
- Texto de CTAs en mayúsculas (`GET STARTED`, `REQUEST A DEMO`) con flechas `>>` (SVG 14px, stroke 1.8).

## Fondos

- **Hero**: `<section class="relative min-h-screen overflow-hidden bg-black">` + contenedor `absolute inset-y-0 left-1/2 w-full max-w-336 -translate-x-1/2 overflow-hidden sm:w-[calc(100%-2rem)] lg:w-[calc(100%-3.5rem)]`.
  - Partículas tipo canvas: componente `GatewayFlow` (iframe `srcDoc` con canvas de curvas Bézier; sirve como sustituto de un canvas three.js). Props útiles: `opacity`, `density`, `speed`.
  - Encima: glow violeta `h-140 w-225 bg-accent/10 blur-[140px]` + glow teal `h-80 w-170 bg-[#5EEAD4]/8 blur-[120px]`, rejilla técnica `bg-grid` con máscara radial, y degradados de contraste `bg-linear-to-r from-black/70 via-black/30 to-transparent` + `bg-linear-to-b from-black/20 via-transparent to-black/60`.
  - El marquee va `absolute bottom-12` dentro del hero.
- **FinalCta**: `PaperDesignBackground` (dithering B/N con `@paper-design/shaders-react`), en contenedor `max-w-336 opacity-60`, `intensity={0.8}`, `absolute inset-0` (no fixed).
- **Grid técnica** (`@utility bg-grid`): líneas `rgba(255,255,255,0.04)` cada 56px con máscara radial opcional.

## Animaciones

Keyframes en `@theme` (Tailwind v4):

```css
--animate-marquee: marquee 42s linear infinite;   /* to { transform: translateX(-50%) } */
--animate-star-btn: star-btn 3s linear infinite;  /* from/to { offset-distance: 0%→100% } */
--animate-budget-scan: budget-meter-scan 5.6s ease-in-out infinite; /* translateX(-110%→420%) */
```

- **Marquee de logos**: fila repetida 4 veces (loop `-50%` sin saltos), `flex w-max` con `gap` igual en contenedor y repeticiones; imágenes `grayscale brightness-0 invert opacity-75` (h-12 md:h-16); máscara lateral `mask-[linear-gradient(to_right,transparent,black_25%,black_75%,transparent)]`.
- **Luz de botón**: `offset-path` + keyframe `star-btn`; permite `animationDuration` por instancia (p. ej. 5s en paneles).
- **Partículas SVG**: usar `<animateMotion dur repeatCount="indefinite" begin path="…"/>` para puntos que recorren caminos (mockup de pipeline).
- **Transiciones interactivas**: solo propiedades concretas (`transition-colors`, `transition-all duration-500` limitado a width/opacity); nada de `transition-all` global ni animaciones en interacciones de alta frecuencia.
- **Reduced motion**: desactivar marquee/animaciones con `@media (prefers-reduced-motion: reduce)` y `MotionConfig reducedMotion="user"` si se usa framer-motion.

## Mockups

- **Sidebar + Gantt** (sección "Stateful execution"): panel `aspect-[1.05] lg:aspect-video` con sidebar `w-[18%]` (logo + nav con iconos lucide `size-3.5` stroke 1.5, texto 11px, ítem activo `bg-white/6`) y Gantt `w-[82%] p-1.25` con `rounded-lg border-white/8 bg-[#101112]`; cabecera de meses `h-17.5` con días `font-mono text-[9px] text-white/24`; carriles con barra `h-6 rounded-md border-white/9 bg-linear-to-b from-white/4.5 to-white/1.8` + relleno de color (`bg-cyan-400/75`, `bg-emerald-400/70`, etc.), hitos (punto + etiqueta 8px) y colas punteadas con `repeating-linear-gradient`.
- **Pipeline**: SVG `viewBox="0 0 580 172"` con nodos `rect rx=8 fill=#141414 stroke=rgba(255,255,255,0.09)` + gradientes metálicos para el orquestador (`#f8fafc→#9ca3af→#e5e7eb→#6b7280`), conexiones `stroke-dasharray="3 5"` con `marker-end` de flecha y partículas `animateMotion`.
- **Schedule**: tarjeta con rejilla de 7 días (`grid-cols-7`, bordes `border-white/5.5`), filas con barras degradadas (cyan/emerald/violet) y pie con métricas mono.
- **Guardrails**: lista de políticas con selector (`border-white/30`, chevron lucide) + panel flotante `w-44 rounded-[14px] border-white/18` con luz recorriendo el borde vía `offset-path: var(--guardrail-beam-path)`.
- **Inbox**: filas `grid-cols-[auto_minmax(0,1fr)_auto]`, avatar 40px con badge de estado (`size-4`, sombra `[0_0_0_2px_rgba(7,7,8,0.95)]`), tiempo `tabular-nums`.

## Checklist al aplicar en un proyecto nuevo

1. Copiar tokens a `index.css` (`@theme`), incluyendo `frame`, `border`, `foreground`, `muted-foreground` y `font-display`.
2. Añadir keyframes `marquee`, `star-btn`, `budget-meter-scan` y utilidades `text-gradient`, `bg-grid`.
3. Recrear `StarButton`, `SectionDivider`, `SideRails`, `CardShell`/marco de tarjeta y `Hairline` como primitivas reutilizables.
4. Montar en el wrapper raíz `relative` los rails; intercalar `SectionDivider` entre secciones.
5. Usar el patrón de encabezado (grid 12, 7/5) en todas las secciones para consistencia.
6. Sustituir los assets de referencia por SVGs locales (logos, avatares) con el mismo tratamiento (`grayscale brightness-0 invert` para logos de marcas).
7. Verificar: contraste de texto sobre fondos oscuros, `prefers-reduced-motion`, `aria-hidden` en decoraciones y `scroll-mt-24` en anclas.

## Common Mistakes

| Error | Corrección |
| --- | --- |
| Borde `#37333b` usado también como separador interior | Usar `border-line` (rgba 255,255,255,0.08) para separadores ligeros |
| Hairline sin el `w-[calc(100%-2.25rem)]` | El hairline siempre deja 18px de margen a cada lado |
| Radio interno igual al externo en marcos anidados | Exterior 14px, interior 8px (radio exterior = interior + padding) |
| `bg-black` puro como fondo de página | Usar `bg-ink` (#050507); el negro puro solo dentro de mockups |
| Marquee con 2 repeticiones y `gap` solo en un nivel | 4 repeticiones y `gap` idéntico en contenedor e hijos para bucle sin salto |
| Animación de luz sin `offset-path` correcto | El path debe aproximar el perímetro real del botón (126×32, 142×40, 248×40) |
| Decoraciones sin `aria-hidden`/`pointer-events-none` | Todas las líneas, ticks y divisores son decorativos |
| Texto de mockups con tamaño ≥12px | Etiquetas técnicas a 8–11px mono para el look de "runtime" |
| Imagen de marca a color en el marquee | `grayscale brightness-0 invert opacity-75` para unificar en blanco |
