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
};
export const roles = ["PLANNER", "APPROVER", "VIEWER"] as const;
export const editableRoles = ["PLANNER", "APPROVER", "ADMIN", "VIEWER"] as const;
export const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
