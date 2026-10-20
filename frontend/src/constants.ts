import { type ConfigTab, type Page } from "./types";

export const pageNames: Record<Page, string> = {
  weekly: "Weekly Baseline Volume",
  promotions: "Promotions",
  calendar: "Promo Calendar",
  history: "Sales Data",
  report: "Volume Report",
  listing: "Product Listing",
  configuration: "Configuration",
};
export const configNames: Record<ConfigTab, string> = {
  access: "Create User ID",
  customer: "Customer Master",
  product: "Product Master",
  tactics: "Tactics",
  phasing: "Phasing",
  files: "Files",
  roles: "Role Definition",
};
export const roleScreens = [
  { id: "weekly", label: "Weekly Baseline Volume", actions: ["view", "edit", "import", "export"] },
  { id: "promotions", label: "Promotions", actions: ["view", "edit", "approve"] },
  { id: "calendar", label: "Promo Calendar", actions: ["view"] },
  { id: "history", label: "Sales Data", actions: ["view", "export"] },
  { id: "report", label: "Volume Report", actions: ["view"] },
  { id: "listing", label: "Product Listing", actions: ["view", "edit"] },
  { id: "configuration", label: "Configuration", actions: ["view", "edit"] },
] as const;
export const roleActions = [
  { id: "view", label: "View" },
  { id: "edit", label: "Edit" },
  { id: "approve", label: "Approve" },
  { id: "import", label: "Import" },
  { id: "export", label: "Export" },
] as const;
export const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
