import { type User } from "./api";

export type Market = {
  code: string;
  name: string;
  plan_mode: "VOL" | "PROMO";
  p10_sales_org: string;
  horizon_weeks: number;
};
export type Customer = { id: number; market_code: string; name: string };
export type Product = {
  code: string;
  description: string;
  brand: string;
  sub_brand: string;
  category: string;
  active?: boolean;
};
export type Tactic = {
  market_code: string;
  name: string;
  incentive_type: "FIXED_LUMPSUM" | "VARIABLE";
};
export type Bootstrap = {
  markets: Market[];
  customers: Customer[];
  products: Product[];
  tactics: Tactic[];
  listings: { market_code: string; customer_id: number; p10_osku: string }[];
  weeks: string[];
  history_weeks: string[];
};
export type BaselineProduct = Product & { baseline: number[]; actual_last_year: number[] };
export type BaselineData = { weeks: string[]; products: BaselineProduct[] };
export type PromotionItem = {
  product: string;
  description: string;
  baseline: number;
  total: number;
  uplift: number;
  actual: number;
};
export type Promotion = {
  id: number;
  version: number;
  promo_number: string;
  market_code: string;
  customer_id: number;
  customer_name: string;
  description: string;
  comments: string;
  start_date: string;
  end_date: string;
  cons_start: string;
  cons_end: string;
  tactic: string;
  incentive_type: "FIXED_LUMPSUM" | "VARIABLE";
  incentive_value: number;
  incentive_configured: boolean;
  status: string;
  baseline: number;
  total: number;
  uplift: number;
  actual: number;
  items: PromotionItem[];
};
export type CalendarPromotion = {
  id: number;
  promo_number: string;
  start_date: string;
  end_date: string;
  tactic: string;
  status: string;
  customer_name: string;
  sub_brand: string;
  product_count: number;
};
export type AccountAssignment = { market_code: string; customer_id: number };
export type AdminUser = User & {
  active: boolean;
  last_login_at: string | null;
  sales_org_access: string[];
  admin_sales_org_access: string[];
};
export type SalesOrg = { code: string; name: string };
export type AccessData = {
  users: AdminUser[];
  assignments: (AccountAssignment & {
    user_id: number;
    customer_name: string;
  })[];
  sales_orgs: SalesOrg[];
};
export type ManagedFile = {
  id: number;
  direction: "INBOUND" | "OUTBOUND";
  category: string;
  original_name: string;
  status: string;
  uploaded_by: string;
  created_at: string;
  processed_at: string | null;
  row_count: number;
  message: string | null;
};
export type Page =
  | "weekly"
  | "promotions"
  | "calendar"
  | "history"
  | "report"
  | "listing"
  | "configuration";
export type ConfigTab = "access" | "customer" | "product" | "tactics" | "phasing" | "files";

export type PageProps = {
  page: Page;
  market: string;
  customerId: number;
  user: User;
  bootstrap: Bootstrap;
  products: Product[];
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
  openPromotionId: number | null;
  onPromotionOpened: () => void;
  onOpenPromotion: (promotionId: number) => void;
};
