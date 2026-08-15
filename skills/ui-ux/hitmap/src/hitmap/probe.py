from __future__ import annotations

PROBE_JS = r'''(() => {
  const selector = [
    'button','input','select','textarea','a[href]',
    '[role="button"]','[role="link"]','[role="checkbox"]','[role="radio"]',
    '[role="switch"]','[role="menuitem"]','[role="tab"]','[tabindex]'
  ].join(',');

  const targetName = (el) => {
    if (!el) return '<none>';
    if (el.id) return '#' + el.id;
    const cls = [...el.classList].slice(0, 2).map(x => '.' + x).join('');
    return el.tagName.toLowerCase() + cls;
  };

  const targetSelector = (el, i) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const testId = el.getAttribute('data-testid');
    if (testId) return `[data-testid="${CSS.escape(testId)}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria) return `${el.tagName.toLowerCase()}[aria-label="${aria.replaceAll('"','\\"')}"]`;
    return `${el.tagName.toLowerCase()}:nth-interactive(${i + 1})`;
  };

  const isAssociatedLabel = (receiver, target) => {
    const label = receiver?.closest?.('label');
    return label instanceof HTMLLabelElement && label.control === target;
  };

  const eligible = (el, rect) => {
    const cs = getComputedStyle(el);
    if (el.matches(':disabled,[aria-disabled="true"],[aria-hidden="true"]')) return false;
    if (el.closest('[inert]')) return false;
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false;
    if (rect.width * rect.height < 16) return false;
    if (rect.right <= 0 || rect.bottom <= 0 || rect.left >= innerWidth || rect.top >= innerHeight) return false;
    return true;
  };

  const points = (rect) => [
    [.50,.50],[.20,.20],[.80,.20],[.20,.80],[.80,.80],
    [.50,.20],[.80,.50],[.50,.80],[.20,.50]
  ].map(([fx,fy]) => [
    Math.round(rect.left + rect.width * fx),
    Math.round(rect.top + rect.height * fy)
  ]);

  return [...document.querySelectorAll(selector)].map((el, i) => {
    const rect = el.getBoundingClientRect();
    const ok = eligible(el, rect);
    const samples = ok ? points(rect).map(([x,y]) => {
      const stack = document.elementsFromPoint(x, y);
      const receiver = stack.find(node => getComputedStyle(node).pointerEvents !== 'none') || null;
      const reachable = !!receiver && (receiver === el || el.contains(receiver) || isAssociatedLabel(receiver, el));
      return {x, y, reachable, receiver: targetName(receiver)};
    }) : [];
    return {
      selector: targetSelector(el, i),
      eligible: ok,
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
      samples
    };
  });
})()'''
