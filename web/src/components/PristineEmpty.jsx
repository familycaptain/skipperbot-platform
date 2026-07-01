import EmptyStateHero from "./EmptyStateHero";
import { isPristineEmpty } from "../apps/emptyStateHero";

/**
 * PristineEmpty — wraps an app's empty-collection branch and shows the
 * onboarding hero only when the slice is truly PRISTINE-empty.
 *
 * Props:
 *   appId, blurb   – forwarded to <EmptyStateHero>.
 *   records        – the slice to judge (the whole collection OR one view's
 *                    slice; the caller passes the relevant slice). null == empty.
 *   loading        – true while the slice is still loading.
 *   filterActive   – true whenever ANY filter that scopes THIS slice is active
 *                    (search text, date/time window, member, tag, effort, …), so
 *                    a filtered/scoped-to-zero view shows `fallback`, never the hero.
 *   fallback       – rendered when NOT pristine-empty (the app's existing
 *                    search/scope-empty text, or null when there is data to show).
 *   children       – the app's existing +New / inline-add. Rendered BELOW the
 *                    hero (footprint capped) so the add stays visible.
 *
 * Serves both whole-collection and per-view placement — the caller decides the slice.
 */
export default function PristineEmpty({
  appId,
  blurb,
  records,
  loading,
  filterActive,
  fallback = null,
  children = null,
}) {
  if (isPristineEmpty({ records, loading, filterActive })) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-6 w-full max-h-full overflow-y-auto">
        <EmptyStateHero appId={appId} blurb={blurb} />
        {children}
      </div>
    );
  }
  return fallback;
}
