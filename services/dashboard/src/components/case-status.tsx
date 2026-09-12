import type { CaseStatus, CaseVerdict } from "@/types/case";

const labels: Record<CaseStatus | CaseVerdict, string> = {
  investigating:"調查中", review:"待審核", fraud:"詐欺", suspicious:"可疑", normal:"正常", unknown:"未判定"
};

export function CaseStatusBadge({ value }: { value: CaseStatus | CaseVerdict }) {
  return <span className={`case-badge ${value}`}><i/>{labels[value]}</span>;
}
