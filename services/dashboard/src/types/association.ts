export interface AssociationEntity {
  id: string;
  label: string;
  entityType?: string;
  riskScore?: number;
  firstObserved?: string;
  caseIds: string[];
  evidenceRefs?: string[];
}

export interface AssociationRelation {
  id: string;
  source: string;
  target: string;
  confidence?: number;
  caseIds: string[];
  evidenceRefs?: string[];
}

export interface AssociationGraphResponse {
  focusEntityId: string;
  strategy: "focused" | "discovery";
  policyRef: { id: string; version: string };
  entities: AssociationEntity[];
  relations: AssociationRelation[];
}
