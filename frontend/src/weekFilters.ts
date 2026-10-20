export const quarterOptions = [
  { value: 1, label: "Q1 (Jan-Mar)" },
  { value: 2, label: "Q2 (Apr-Jun)" },
  { value: 3, label: "Q3 (Jul-Sep)" },
  { value: 4, label: "Q4 (Oct-Dec)" },
];

export function isoWeekThursday(week: string): Date {
  const [yearText, weekText] = week.split("-W");
  const januaryFourth = new Date(Date.UTC(Number(yearText), 0, 4));
  const mondayOffset = (januaryFourth.getUTCDay() + 6) % 7;
  return new Date(Date.UTC(
    Number(yearText),
    0,
    4 + (Number(weekText) - 1) * 7 - mondayOffset + 3,
  ));
}

export function weekLabel(week: string): string {
  const [year, weekNumber] = week.split("-W");
  return `Week ${Number(weekNumber)} ${year}`;
}

export function weekDateRange(week: string): string {
  const thursday = isoWeekThursday(week);
  const monday = new Date(Date.UTC(
    thursday.getUTCFullYear(),
    thursday.getUTCMonth(),
    thursday.getUTCDate() - 3,
  ));
  const sunday = new Date(Date.UTC(
    monday.getUTCFullYear(),
    monday.getUTCMonth(),
    monday.getUTCDate() + 6,
  ));
  const format = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
  return `${format.format(monday)} – ${format.format(sunday)}`;
}
