# PaperManager — UI Style Guide

> **Single source of truth for all frontend styling decisions.**
> Tokens are defined in [`frontend/src/index.css`](../frontend/src/index.css) via Tailwind v4 `@theme`.
> When in doubt, use a semantic token instead of a raw Tailwind color.

---

## 1. Design Tokens

These are the only colors you should use for structure and text. They map to fixed Tailwind values and support future theming (e.g. dark mode) by changing one place.

### Surfaces

| Token | Class | Value | Use for |
|---|---|---|---|
| raised | `bg-raised` | `#ffffff` white | Cards, modals, dropdowns |
| base | `bg-base` | `#f9fafb` gray-50 | Page background |

### Text

| Token | Class | Value | Use for |
|---|---|---|---|
| ink | `text-ink` | `#111827` gray-900 | Headings, primary labels |
| ink-2 | `text-ink-2` | `#4b5563` gray-600 | Body text, secondary labels |
| ink-3 | `text-ink-3` | `#9ca3af` gray-400 | Muted text, placeholders, hints |

### Borders

| Token | Class | Value | Use for |
|---|---|---|---|
| line | `border-line` | `#e5e7eb` gray-200 | Standard borders on inputs, cards |
| line-s | `border-line-s` | `#f3f4f6` gray-100 | Subtle dividers inside panels |

### Accent (violet brand)

| Token | Class | Value | Use for |
|---|---|---|---|
| accent | `bg-accent` / `text-accent` / `border-accent` | `#7c3aed` violet-600 | Primary buttons, active states, links |
| accent-lo | `bg-accent-lo` | `#f5f3ff` violet-50 | Selected row backgrounds, tinted surfaces |
| accent-border | `border-accent-border` | `#ddd6fe` violet-200 | Subtle violet borders on focus/hover |

### Semantic feedback

| Token | Class | Value | Use for |
|---|---|---|---|
| coral | `text-coral` | `#dc2626` red-600 | Error messages, destructive text |
| amber | `text-amber` | `#d97706` amber-600 | Warning text |

---

## 2. Typography

Never hard-code `text-gray-*` for text. Use the ink scale instead.

```
text-[10px] font-semibold text-accent uppercase tracking-wide   ← section eyebrow / badge label
text-sm font-semibold text-ink                                  ← modal / card heading
text-sm text-ink-2                                              ← body copy
text-xs font-medium text-ink-3 uppercase tracking-wide          ← sub-section label
text-xs text-ink-3                                              ← helper text, subtitles, hints
text-[11px] text-ink-3                                          ← very small metadata
```

---

## 3. Buttons

### Primary
```tsx
className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700 disabled:opacity-50"
```

### Secondary (outline)
```tsx
className="px-4 py-2 text-sm border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent"
```

### Ghost (skip / cancel)
```tsx
className="px-4 py-2 text-sm text-ink-3 hover:text-ink"
```

### Destructive
```tsx
// Default state
className="border border-line text-ink-3 hover:text-coral hover:border-red-300 ..."
// Confirmed (after first click)
className="bg-red-600 border-red-600 text-white ..."
```

### Icon button
```tsx
className="p-1.5 rounded border border-line text-ink-3 hover:text-accent hover:border-accent-border transition-colors"
```

---

## 4. Inputs & Form Elements

### Text input
```tsx
className="w-full border border-line rounded px-3 py-1.5 text-sm
           focus:outline-none focus:ring-2 focus:ring-violet-300"
```

### Textarea
```tsx
className="w-full border border-line rounded px-3 py-1.5 text-sm
           focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none"
```

### Select
```tsx
className="border border-line rounded px-2 py-1.5 text-sm bg-raised text-ink-2
           focus:outline-none focus:ring-2 focus:ring-violet-300"
```

### Field wrapper
```tsx
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-ink-3 mb-1">{label}</label>
      {children}
    </div>
  );
}
```

---

## 5. Badges & Pills

### Tag (toggleable)
```tsx
// Active / applied
className="px-3 py-1 rounded-full text-xs font-medium border bg-accent text-white border-accent"

// Inactive
className="px-3 py-1 rounded-full text-xs font-medium border
           bg-raised text-ink-2 border-line hover:border-accent-border hover:text-accent"
```

### Topic pill
```tsx
className="px-2.5 py-1 text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full"
```

### Person / author pill
```tsx
className="px-2.5 py-1 text-xs bg-accent-lo text-accent border border-accent-border rounded-full"
```

### Reading status badge
```
unread:  bg-gray-100 text-gray-500
reading: bg-blue-100 text-blue-600
read:    bg-green-100 text-green-600
```

### Metadata source badge
```
semantic_scholar / crossref: bg-green-100 text-green-700
llm:                         bg-yellow-100 text-yellow-700
heuristic:                   bg-red-100 text-red-700
```

---

## 6. Cards

### Paper card
```tsx
className="bg-raised border border-line rounded-lg p-4 cursor-pointer
           hover:shadow-md hover:border-accent-border transition-all"
```

### Panel / section box
```tsx
className="bg-raised border border-line rounded-xl p-4"
```

### Tinted section (inside a card/modal)
```tsx
className="bg-base rounded-lg border border-line p-3"
```

---

## 7. Modals

All modals share the same structural shell:

```tsx
{/* Backdrop */}
<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">

  {/* Panel */}
  <div className="bg-raised rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">

    {/* Header */}
    <div className="px-6 py-4 border-b border-line-s">
      <div className="flex items-center justify-between mb-0.5">
        <h2 className="font-semibold text-ink">{title}</h2>
        <button onClick={onClose} className="text-ink-3 hover:text-ink-2 text-lg leading-none">×</button>
      </div>
      <p className="text-xs text-ink-3">{subtitle}</p>
    </div>

    {/* Content */}
    <div className="px-6 py-4 space-y-3">
      ...
    </div>

    {/* Footer */}
    <div className="px-6 py-4 border-t border-line-s flex justify-end gap-2">
      <button className="px-4 py-2 text-sm text-ink-3 hover:text-ink">Cancel</button>
      <button className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-violet-700">Save</button>
    </div>

  </div>
</div>
```

**Multi-step modals** add a `StepDots` component above the subtitle:

```tsx
function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex gap-1 items-center">
      {Array.from({ length: total }).map((_, i) => (
        <span key={i} className={`w-1.5 h-1.5 rounded-full transition-colors ${
          i === current ? "bg-accent" : i < current ? "bg-violet-300" : "bg-line"
        }`} />
      ))}
    </div>
  );
}
```

---

## 8. Inline Feedback

### Success
```tsx
<p className="text-xs text-green-600 font-medium">✓ Saved successfully.</p>
```

### Error / validation
```tsx
<p className="text-xs text-coral">{error}</p>
```

### Warning banner
```tsx
<div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
  <p className="text-xs font-medium text-amber-800">...</p>
  <p className="text-xs text-amber">...</p>
</div>
```

### Duplicate / info banner
```tsx
<div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 text-xs">
  <span className="text-amber mt-0.5 shrink-0">⚠</span>
  <span className="text-amber-800">...</span>
</div>
```

### Loading pulse
```tsx
<p className="text-xs text-ink-3 animate-pulse">Loading…</p>
```

---

## 9. Spacing & Sizing Conventions

| Element | Value |
|---|---|
| Modal max width | `max-w-lg` (512px) |
| Modal horizontal padding | `px-6` |
| Section gap inside modal | `space-y-3` or `space-y-4` |
| Card padding | `p-4` |
| Input height | `py-1.5` → ~34px |
| Button height (standard) | `py-2` → ~36px |
| Icon button size | `p-1.5` with `w-3.5 h-3.5` icon |
| Nav button size | `h-9 w-9` |
| Tag/pill gap | `gap-1.5` or `gap-2` |

---

## 10. Do / Don't

| ✅ Do | ❌ Don't |
|---|---|
| `text-ink` | `text-gray-900` (for UI text) |
| `bg-raised` | `bg-white` (for card/modal bg) |
| `border-line` | `border-gray-200` (for structural borders) |
| `text-accent` | `text-violet-600` (for brand accent) |
| `bg-accent text-white` for primary buttons | `bg-violet-600 text-white` |
| `hover:bg-violet-700` for button hover | `hover:bg-accent` (no visual change) |
| `text-coral` for errors | `text-red-600` |
| `rounded-xl` for panels/modals | `rounded-2xl` (inconsistent sizing) |
| `shadow-xl` for modals | `shadow-2xl` (too heavy) |

> **Raw Tailwind colors are still fine for:** data visualisation (chart bars, stat cards), reading-status badges, metadata-source badges, and other domain-specific colour coding that isn't part of the structural UI chrome.
