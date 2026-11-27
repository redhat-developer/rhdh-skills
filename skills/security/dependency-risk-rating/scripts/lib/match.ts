// Package-name pattern matching: exact names or trailing-* globs like "@scope/*".

export function matchPattern(name: string, pattern: string): boolean {
  if (pattern === name) return true;
  if (!pattern.includes('*')) return false;
  const regex = new RegExp(
    '^' + pattern.split('*').map(escapeRegExp).join('.*') + '$',
  );
  return regex.test(name);
}

export function matchAny(name: string, patterns: string[] | undefined | null): boolean {
  if (!patterns) return false;
  return patterns.some((p) => matchPattern(name, p));
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
