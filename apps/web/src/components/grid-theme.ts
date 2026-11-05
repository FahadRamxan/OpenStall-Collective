import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

/** AG Grid in the site's own colours, light and dark, from the same tokens as the rest of the page. */
export const GRID_THEME = themeQuartz.withParams({
  backgroundColor: "var(--surface)",
  foregroundColor: "var(--foreground)",
  textColor: "var(--foreground)",
  borderColor: "var(--border)",
  accentColor: "var(--accent)",
  headerBackgroundColor: "var(--background)",
  headerTextColor: "var(--muted)",
  rowHoverColor: "var(--accent-soft)",
  fontFamily: "inherit",
  fontSize: 14,
  wrapperBorderRadius: 12,
});

/** Wrapped text at the page's own line height, not the grid's row height, with room above and below. */
export const WRAPPED = { lineHeight: "1.375rem", paddingTop: "0.625rem", paddingBottom: "0.625rem" };
