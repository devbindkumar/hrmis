import { cn } from "@/lib/utils";

const LABELS = {
  present: "Present",
  absent: "Absent",
  remote: "Remote",
  on_leave: "On Leave",
  in_meeting: "In Meeting",
  on_break: "On Break",
  offline: "Offline",
  active: "Active",
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
};

export default function StatusPill({ status, label, className }) {
  const key = status || "offline";
  return (
    <span
      data-testid={`status-pill-${key}`}
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium",
        `pill-${key}`,
        className
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {label || LABELS[key] || key}
    </span>
  );
}
