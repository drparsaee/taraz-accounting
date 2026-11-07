/** Progressive floating captions, outside of all React-owned form subtrees.
 *
 * Call installFloatingLabels(document) once from each Vite entrypoint, after
 * createRoot(...).render(...); import floating_labels.css after other styles.
 * React can update/remove its original inputs and labels normally.
 */

const FIELD_SELECTOR = 'input, textarea, select';
const NON_TEXT_TYPES = new Set([
  'hidden', 'checkbox', 'radio', 'file', 'color', 'range', 'button', 'reset',
  'submit', 'image', 'search',
]);
// These components provide their own input chrome and/or an adjacent label.
// An extra portal caption would overlap the icon, currency suffix or action.
const COMPOSITE_FIELD_SELECTOR = [
  '[data-no-floating-label]', '.searchplus-shell', '.search-box',
  '.money-input', '.inline-create', '.filter-select',
  '.stage-edit-fields', '.stage-new', '.kanban-add-list__form',
  '.lane-actions-popover__editor',
].join(', ');
const ALWAYS_RAISED_TYPES = new Set([
  'date', 'datetime-local', 'time', 'month', 'week',
]);

const clean = text => String(text ?? '').replace(/\s+/g, ' ').trim();

export function isFloatingCandidate(control) {
  if (!control || !['INPUT', 'TEXTAREA', 'SELECT'].includes(control.tagName)) return false;
  if (control.tagName === 'INPUT' && NON_TEXT_TYPES.has(control.type?.toLowerCase())) return false;
  if (control.closest?.(`[inert], [aria-hidden="true"], ${COMPOSITE_FIELD_SELECTOR}`)) return false;
  // A separate or compound native label is already visible beside this field.
  // Floating it as well produces duplicate text (and can hide instructions).
  if (Array.from(control.labels || []).some(label => !isSimpleWrappingLabel(label, control))) return false;
  // An input without a real visible box (e.g. a hidden autocomplete helper)
  // must not acquire a visual overlay.
  return true;
}

function visibleLabelText(label, control) {
  if (!label?.childNodes) return '';
  const portions = [];
  for (const node of label.childNodes) {
    if (node === control || (node.nodeType === 1 && node.contains(control))) continue;
    if (node.nodeType === 3) portions.push(node.textContent);
    else if (node.nodeType === 1 &&
      !node.matches('input, textarea, select, button, [aria-hidden="true"], .madar-fl-caption') &&
      !node.querySelector('input, textarea, select, button')) {
      portions.push(node.textContent);
    }
  }
  return clean(portions.join(' '));
}

export function floatingLabelText(control, documentRoot = globalThis.document, ignoreAriaLabel = false) {
  const nativeLabels = Array.from(control.labels || []);
  for (const label of nativeLabels) {
    const text = visibleLabelText(label, control);
    if (text) return text;
  }
  const labelledBy = control.getAttribute('aria-labelledby');
  if (labelledBy && documentRoot?.getElementById) {
    const text = clean(labelledBy.split(/\s+/).map(id =>
      documentRoot.getElementById(id)?.textContent || '').join(' '));
    if (text) return text;
  }
  return clean((!ignoreAriaLabel && control.getAttribute('aria-label')) ||
    control.getAttribute('data-floating-label') ||
    control.getAttribute('placeholder') ||
    control.getAttribute('title'));
}

function isSimpleWrappingLabel(label, control) {
  if (label?.tagName !== 'LABEL' || control.parentElement !== label) return false;
  // Don't collapse compound labels with helper text, toggles, or more fields.
  const otherNodes = Array.from(label.children).filter(node =>
    node !== control && !node.classList.contains('madar-fl-caption'));
  return otherNodes.every(node =>
    node.tagName === 'SPAN' && !node.querySelector(FIELD_SELECTOR + ', button, a, [role="button"]')) &&
    otherNodes.length <= 1;
}

function syncCaption(state) {
  const { control, caption } = state;
  const valuePresent = control.tagName === 'SELECT' ||
    Boolean(control.value) || control.matches(':focus') ||
    ALWAYS_RAISED_TYPES.has(control.type?.toLowerCase());
  caption.classList.toggle('madar-fl-raised', valuePresent);
  caption.classList.toggle('madar-fl-invalid', control.getAttribute('aria-invalid') === 'true');
  caption.classList.toggle('madar-fl-disabled', control.disabled);
}

const CLIPPING_OVERFLOW = /^(?:auto|scroll|hidden|clip|overlay)$/;

/** A fixed portal does not inherit clipping from scroll containers. Require
 * the entire field to fit in the viewport AND every clipping ancestor before
 * drawing a caption. This avoids a caption bleeding into unrelated rows when
 * a partially hidden field crosses a sticky header or a modal scroll edge. */
export function isFieldFullyVisible(control, rect, view) {
  if (rect.width < 45 || rect.height < 30 ||
      rect.left < 0 || rect.top < 0 ||
      rect.right > view.innerWidth || rect.bottom > view.innerHeight ||
      rect.right <= rect.left || rect.bottom <= rect.top) return false;

  for (let ancestor = control.parentElement; ancestor; ancestor = ancestor.parentElement) {
    const style = view.getComputedStyle(ancestor);
    const overflowX = style.overflowX || style.overflow || 'visible';
    const overflowY = style.overflowY || style.overflow || 'visible';
    const paintContain = /(?:^|\s)paint(?:\s|$)/.test(style.contain || '');
    const xClips = CLIPPING_OVERFLOW.test(overflowX) || paintContain;
    const yClips = CLIPPING_OVERFLOW.test(overflowY) || paintContain;
    if (!xClips && !yClips) continue;
    const bounds = ancestor.getBoundingClientRect();
    // client{Width,Height} omit scrollbar and border, matching the true
    // scrollport. Fallback only for non-layout test doubles.
    const left = bounds.left + (ancestor.clientLeft || 0);
    const top = bounds.top + (ancestor.clientTop || 0);
    const right = left + (ancestor.clientWidth ?? bounds.width);
    const bottom = top + (ancestor.clientHeight ?? bounds.height);
    // Tiny rounding differences from fractional CSS pixels are tolerated.
    if ((xClips && (rect.left < left - 0.5 || rect.right > right + 0.5)) ||
        (yClips && (rect.top < top - 0.5 || rect.bottom > bottom + 0.5))) {
      return false;
    }
  }
  return true;
}

/** Fixed captions follow visible controls in the same animation frame.
 * They live outside React's root and retain its original DOM ownership. */
function positionCaption(state, activeModal) {
  const { control, caption } = state;
  const rect = control.getBoundingClientRect();
  const view = control.ownerDocument.defaultView;
  const behindModal = activeModal && !activeModal.contains(control);
  if (behindModal || !isFieldFullyVisible(control, rect, view)) {
    caption.hidden = true;
    return;
  }
  caption.hidden = false;
  const right = Math.max(0, view.innerWidth - rect.right + 9);
  const top = rect.top + 7;
  const middle = rect.top + rect.height / 2;
  caption.style.setProperty('--madar-fl-right', `${right}px`);
  caption.style.setProperty('--madar-fl-top-y', `${top}px`);
  caption.style.setProperty('--madar-fl-mid-y', `${middle}px`);
  caption.style.setProperty('--madar-fl-width', `${Math.max(0, rect.width - 25)}px`);
}

export function installFloatingLabels(root = globalThis.document) {
  if (!root?.querySelectorAll || !root?.addEventListener) return () => {};
  const doc = root.nodeType === 9 ? root : root.ownerDocument;
  const view = doc.defaultView;
  if (!view?.MutationObserver || !view.requestAnimationFrame) return () => {};
  const appRoot = root.nodeType === 9 ? doc.getElementById('root') || doc.body : root;
  if (!appRoot) return () => {};
  const layer = doc.createElement('div');
  layer.className = 'madar-fl-layer';
  layer.setAttribute('aria-hidden', 'true');
  doc.body.appendChild(layer);
  const fields = new Map();
  let pending = false;
  let disposed = false;
  let dirty = true;
  const observedAncestors = new Map();

  const observer = new view.MutationObserver(records => {
    if (disposed) return;
    let needsScan = false;
    let layoutChanged = false;
    for (const record of records) {
      if (record.type === 'childList') {
        // A deleted stage can move other fields even when its nodes contain
        // no inputs. React may also move an existing input to another row.
        layoutChanged = true;
        if (Array.from(record.addedNodes || []).concat(Array.from(record.removedNodes || []))
          .some(node => node.nodeType === 1 &&
            (node.matches?.(FIELD_SELECTOR + ', label') || node.querySelector?.(FIELD_SELECTOR + ', label')))) {
          needsScan = true;
        }
      } else if (record.type === 'characterData') {
        layoutChanged = true;
        if (record.target.parentElement?.closest('label')) needsScan = true;
      } else if (record.type === 'attributes') {
        if (['class', 'style', 'hidden', 'dir', 'open'].includes(record.attributeName)) {
          layoutChanged = true;
          // Adding a composite wrapper or native label changes eligibility,
          // even if the field itself never rerenders.
          if (record.attributeName === 'class' &&
              (record.target?.matches?.(FIELD_SELECTOR) || record.target?.querySelector?.(FIELD_SELECTOR))) {
            needsScan = true;
          }
        } else {
          needsScan = true;
        }
      }
    }
    // MutationObserver callbacks run before the next paint. Remove orphaned
    // portal captions here instead of leaving them over unrelated rows until
    // the next animation frame.
    for (const control of fields.keys()) {
      if (control.isConnected === false || appRoot.contains?.(control) === false) {
        remove(control);
        layoutChanged = true;
        needsScan = true;
      }
    }
    if (needsScan || layoutChanged) {
      // The old fixed coordinates must never be painted with a new row layout.
      if (layoutChanged) layer.style.visibility = 'hidden';
      schedule(needsScan);
    }
  });
  const resizeObserver = view.ResizeObserver ? new view.ResizeObserver(() => {
    layer.style.visibility = 'hidden';
    schedule(false);
  }) : null;

  function syncObservedAncestors(state) {
    if (!resizeObserver) return;
    const next = [];
    for (let node = state.control.parentElement; node; node = node.parentElement) {
      next.push(node);
      if (node === appRoot) break;
    }
    const previous = state.ancestors || [];
    for (const node of previous) {
      if (next.includes(node)) continue;
      const remaining = observedAncestors.get(node) - 1;
      if (remaining) observedAncestors.set(node, remaining);
      else {
        observedAncestors.delete(node);
        resizeObserver.unobserve(node);
      }
    }
    for (const node of next) {
      if (previous.includes(node)) continue;
      const uses = observedAncestors.get(node) || 0;
      if (!uses) resizeObserver.observe(node);
      observedAncestors.set(node, uses + 1);
    }
    state.ancestors = next;
  }

  function remove(control) {
    const state = fields.get(control);
    if (!state) return;
    state.caption.remove();
    control.classList.remove('madar-fl-control');
    control.style.removeProperty('--madar-fl-control-font');
    if (state.generatedAriaLabel && control.getAttribute('aria-label') === state.label) {
      control.removeAttribute('aria-label');
    }
    if (state.nativeLabel) {
      state.nativeLabel.classList.remove('madar-fl-native-label');
      state.sourceSpan?.classList.remove('madar-fl-original-caption');
    }
    const ancestors = state.ancestors || [];
    state.ancestors = [];
    for (const node of ancestors) {
      const remaining = observedAncestors.get(node) - 1;
      if (remaining) observedAncestors.set(node, remaining);
      else {
        observedAncestors.delete(node);
        resizeObserver?.unobserve(node);
      }
    }
    resizeObserver?.unobserve(control);
    fields.delete(control);
  }

  function add(control, activeModal) {
    if (!isFloatingCandidate(control) || !control.parentElement) return;
    const label = floatingLabelText(control, doc);
    if (!label) return; // Never invent an accessible name from a variable name.
    const caption = doc.createElement('span');
    caption.className = 'madar-fl-caption';
    caption.setAttribute('aria-hidden', 'true');
    caption.textContent = label;
    const nativeLabel = control.closest('label');
    const simple = isSimpleWrappingLabel(nativeLabel, control) ? nativeLabel : null;
    const sourceSpan = simple && Array.from(simple.children).find(node =>
      node.tagName === 'SPAN' && node !== caption);
    // A native label is already the correct accessible name. Never replace
    // its semantics or click target with a synthesized aria-label.
    const generatedAriaLabel = !control.getAttribute('aria-label') &&
      !control.getAttribute('aria-labelledby') && !control.labels?.length;
    if (generatedAriaLabel) control.setAttribute('aria-label', label);

    const font = view.getComputedStyle(control).fontSize;
    control.style.setProperty('--madar-fl-control-font', font);
    control.classList.add('madar-fl-control');
    if (simple) {
      simple.classList.add('madar-fl-native-label');
      sourceSpan?.classList.add('madar-fl-original-caption');
    }
    // The caption is a portal sibling of #root, never a React child.
    layer.appendChild(caption);
    const state = {control, caption, label, nativeLabel:simple, sourceSpan, generatedAriaLabel};
    fields.set(control, state);
    resizeObserver?.observe(control);
    syncObservedAncestors(state);
    syncCaption(state);
    positionCaption(state, activeModal);
  }

  function scan() {
    if (disposed) return;
    const activeModal = doc.querySelector('.overlay, .drawer-overlay, [aria-modal="true"]');
    const found = new Set(appRoot.querySelectorAll(FIELD_SELECTOR));
    for (const control of fields.keys()) {
      if (!found.has(control) || !control.isConnected || !isFloatingCandidate(control)) remove(control);
    }
    for (const control of found) {
      const state = fields.get(control);
      if (!state) add(control, activeModal);
      else {
        syncObservedAncestors(state);
        // An aria-label that we previously generated should not obscure
        // updates to the underlying placeholder or data-floating-label.
        const ownAriaLabel = state.generatedAriaLabel && control.getAttribute('aria-label') === state.label;
        if (ownAriaLabel && control.labels?.length) {
          control.removeAttribute('aria-label');
          state.generatedAriaLabel = false;
        } else if (state.generatedAriaLabel && !ownAriaLabel) {
          state.generatedAriaLabel = false;
        }
        const next = floatingLabelText(control, doc, ownAriaLabel);
        if (!next) {
          remove(control);
          continue;
        }
        if (next && next !== state.label) {
          state.label = next;
          state.caption.textContent = next;
          if (state.generatedAriaLabel) control.setAttribute('aria-label', next);
        }
        syncCaption(state);
        positionCaption(state, activeModal);
      }
    }
  }

  function schedule(fullScan = false) {
    if (disposed) return;
    if (fullScan) dirty = true;
    if (pending) return;
    pending = true;
    view.requestAnimationFrame(() => {
      pending = false;
      if (disposed) return;
      try {
        if (dirty) { dirty = false; scan(); }
        else {
          const activeModal = doc.querySelector('.overlay, .drawer-overlay, [aria-modal="true"]');
          for (const state of fields.values()) positionCaption(state, activeModal);
        }
      } finally {
        // Keep the entire portal hidden during scroll until the positions
        // and clipping states have been recomputed in this paint cycle.
        layer.style.visibility = '';
      }
    });
  }
  function onFieldEvent(event) {
    const state = fields.get(event.target);
    if (state) syncCaption(state);
    else if (event.target?.matches?.(FIELD_SELECTOR)) schedule(true);
    if (event.type === 'focusout') view.requestAnimationFrame(() => {
      if (!disposed && fields.has(event.target)) syncCaption(fields.get(event.target));
    });
  }
  const onScroll = () => {
    layer.style.visibility = 'hidden';
    schedule(false);
  };
  appRoot.addEventListener('focusin', onFieldEvent, true);
  appRoot.addEventListener('focusout', onFieldEvent, true);
  appRoot.addEventListener('input', onFieldEvent, true);
  appRoot.addEventListener('change', onFieldEvent, true);
  doc.addEventListener('scroll', onScroll, true);
  view.addEventListener('resize', onScroll);
  observer.observe(appRoot, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['aria-label', 'aria-labelledby', 'aria-hidden', 'inert', 'data-no-floating-label', 'data-floating-label', 'placeholder', 'title', 'id', 'for', 'type', 'aria-invalid', 'disabled', 'class', 'style', 'hidden', 'dir', 'open'],
  });
  schedule(true);

  return () => {
    disposed = true;
    observer.disconnect();
    resizeObserver?.disconnect();
    appRoot.removeEventListener('focusin', onFieldEvent, true);
    appRoot.removeEventListener('focusout', onFieldEvent, true);
    appRoot.removeEventListener('input', onFieldEvent, true);
    appRoot.removeEventListener('change', onFieldEvent, true);
    doc.removeEventListener('scroll', onScroll, true);
    view.removeEventListener('resize', onScroll);
    for (const control of Array.from(fields.keys())) remove(control);
    layer.remove();
  };
}
