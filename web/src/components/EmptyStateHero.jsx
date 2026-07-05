import { getAppManifest } from "../apps/registry";

/**
 * EmptyStateHero — the pristine-empty onboarding hero for a record-based app.
 *
 * Props:
 *   appId – registry ENTRY id; resolves {icon,name} via getAppManifest(appId)
 *   blurb – operator-final one-liner. Passed as a prop (not read from the
 *           manifest) so a per-view hero can supply that view's own copy.
 *   title – OPTIONAL heading override. When omitted the app name (from the
 *           manifest) is used. A per-view hero passes the view's own title
 *           (e.g. the Nags tab passes "Nags") so a multi-hero app can label
 *           each hero for its view instead of repeating the app name.
 *
 * Renders a CENTERED, calm hero — the app's Lucide icon (~40px, faint/reduced
 * opacity like the existing dimmed empty-state icons), the app name as a heading
 * in the STRONG text token (--ds-text), and the blurb in the faint token — all
 * inside a max-w-md wrapper using design-system --ds-* tokens ONLY, so it themes
 * light + dark automatically. Explicit per-element tokens keep the name strong
 * (never flattened to the faint empty-state default).
 *
 * Renders null when there is no blurb (nothing to say = no hero). Name + blurb
 * are plain JSX text — never dangerouslySetInnerHTML.
 */
export default function EmptyStateHero({ appId, blurb, title }) {
  if (!blurb) return null;

  const manifest = getAppManifest(appId);
  if (!manifest) return null;

  const Icon = manifest.icon;
  const heading = title || manifest.name;

  return (
    <div className="flex flex-col items-center justify-center text-center max-w-md mx-auto px-4 py-6">
      {Icon && (
        <Icon
          size={40}
          strokeWidth={1.5}
          aria-hidden="true"
          className="mb-3"
          style={{ color: "var(--ds-faint)", opacity: 0.55 }}
        />
      )}
      <h2 className="text-base font-semibold mb-1.5" style={{ color: "var(--ds-text)" }}>
        {heading}
      </h2>
      <p className="text-sm leading-relaxed" style={{ color: "var(--ds-faint)" }}>
        {blurb}
      </p>
    </div>
  );
}
