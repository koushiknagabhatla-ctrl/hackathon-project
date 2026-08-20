/**
 * The Auralis component surface. Lane E imports from here and nowhere deeper:
 *
 *   import { IncidentCard, ClaimBlock, EvidenceChip, useToast } from "@/components/ui";
 */

export { Icon, type IconName, type IconProps } from "./Icon";
export { EvidenceChip, EvidenceChipRow, type EvidenceChipProps } from "./EvidenceChip";
export { ClaimBlock, type ClaimBlockProps } from "./ClaimBlock";
export { RiskBadge, type RiskBadgeProps } from "./RiskBadge";
export {
  IncidentCard,
  SEVERITY_META,
  INCIDENT_STATE_LABEL,
  type IncidentCardProps,
} from "./IncidentCard";
export { MetricTile, type MetricTileProps } from "./MetricTile";
export {
  ApprovalControl,
  type ApprovalControlProps,
  type ApprovalDecision,
} from "./ApprovalControl";
export { Drawer, type DrawerProps } from "./Drawer";
export {
  ToastProvider,
  useToast,
  type ToastInput,
  type ToastTone,
} from "./Toast";
export { Skeleton, type SkeletonProps, type SkeletonVariant } from "./Skeleton";
export { StaleBadge, type StaleBadgeProps } from "./StaleBadge";
export { SyntheticBanner, type SyntheticBannerProps } from "./SyntheticBanner";
export { EmptyState, type EmptyStateProps } from "./EmptyState";
export { ErrorState, type ErrorStateProps } from "./ErrorState";
