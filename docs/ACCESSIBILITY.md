# Accessibility

OpenWarframe aims for WCAG 2.1 AA in the app window and the HTML exports. This page says what works
today, what doesn't yet, and how we keep it from slipping.

## What works

- **Keyboard:** every view, tab, filter, table row and button works with Tab, Enter and Space.
  Table rows take focus and carry `aria-expanded`; focus returns to the same control after the page
  redraws. `/` jumps to search, `?` lists the shortcuts, Esc closes dialogs.
- **Screen readers:** the consent prompt is a real modal `<dialog>`; toasts and the reward pick are
  announced through `role="status"` live regions; tabs use the tab pattern.
- **Text size:** Settings offers 100% to 200% text, with a 13 px minimum for small labels. The
  pop-out window follows the same setting.
- **Contrast:** text and pill colours meet 4.5:1 in both light and dark themes, and a high-contrast
  option raises it further. A test (`tests/test_accessibility.py`) checks the theme colours on every
  pull request.
- **Calm mode:** a No motion setting turns off every animation, and the Focus view shows one next action at a time.
- **Words:** game terms (Radiant, rotation A, vaulted, …) have a glossary on the Focus view.

## Known gaps

- The reward helper reads the game screen; its result is shown and announced, but a screen-reader
  user still has to pick the reward in the game itself.
- The Excel and Word exports use built-in styles; their colour fills haven't been checked against
  every Office theme.
- There is no full automated audit (such as axe) in CI yet; the contrast and labelling tests cover
  the theme and the page's static markup only.
- The UI is English only; the reward helper reads every game language. See [I18N.md](I18N.md).

## Checklist for changes to the page

Before opening a pull request that changes the page (`index.html`, `static/page/`) or `mini.html`:

1. Every new control is a `<button>`, `<a>` or form field (no clickable `<div>`), with visible
   text or an `aria-label`.
2. New colours are theme tokens (`--…` in `:root` and both dark blocks); the contrast test passes.
3. Re-rendering keeps focus where it was (use a `data-` key the focus restorer knows).
4. Anything that appears by itself (a toast, a result) is in a `role="status"` region.
5. It works at 200% text and at the 900 px minimum window width.
6. Try it with the keyboard only, once.

Found a barrier? Open an issue with the label `accessibility`.
