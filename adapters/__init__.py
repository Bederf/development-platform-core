"""Adapters that translate platform declarations into normalized contexts."""

from .agent_adapter import AgentAdapter, AgentAdapterError, AgentAdapterRequest
from .capability_projection import CapabilityProjectionError, build_skill_projection_plan
from .agent_runtime import (
    AgentExecutionIdentity,
    AgentRuntimeIdentityBridge,
    AgentRuntimeIdentityError,
    ProviderSessionObservation,
)
from .agent_evidence import AgentEvidenceError, AgentLifecycle, ArtifactCollector, ArtifactRecord, LifecycleEvent
from .humanizer import HumanizerAdapter, HumanizerAdapterError, HumanizerBundle, HumanizerRequest
from .humanizer_deterministic import ConservativeHumanizerProvider
from .humanizer_rules import RuleBasedHumanizerProvider
from .humanizer_artifacts import (
    HumanizerAdoptionDecision,
    HumanizerArtifactError,
    HumanizerArtifactStore,
    StoredHumanizerArtifacts,
    assess_humanizer_adoption,
)
from .humanizer_forge import HumanizerForgeCoordinator, HumanizerForgeError, HumanizerForgeOutcome
from .humanizer_python_rules import rename_python_identifier, rename_python_lambda_parameter
from .humanizer_profiles import (
    HumanizerProfile,
    HumanizerProfileError,
    build_rules_for_profile,
    load_humanizer_profile,
)
from .code_review import CodeReviewError, FakeCodeReviewAgent
from .code_review_context import ReviewContextError, ReviewPackage, build_review_package
from .code_review_provider import CodeReviewProviderAdapter, CodeReviewProviderError
from .independent_review import IndependentReviewAdapter, IndependentReviewError
from .review_cycle import FakeReviewCycleCoordinator, ReviewCycleError
from .review_loop import ReviewLoopDecision, ReviewLoopPolicyError, plan_next_action
from .completion_gate import CompletionDecision, assess_completion
from .review_requirements import RequirementGateDecision, assess_requirements
from .governance_profile import independent_review_required
from .dsh_runtime import DshExecutionRecord, DshRuntimeAdapter, DshRuntimeError
from .forge_request import ForgeRequestAdapter, ForgeRequestError
from .risk_adjusted_forge import (
    RiskAdjustedForgeError,
    RiskAdjustedForgePlan,
    build_risk_adjusted_forge_request,
    render_forge_manifest,
    validate_risk_adjusted_forge_request,
)
from .gsd_lifecycle import GsdLifecycleAdapter, GsdLifecycleError
from .gsd_execution_model import GsdExecutionModelError, authorize_phase_execution
from .phase_specification import (
    SkillResolution,
    resolve_skill_identity,
    validate_execution_plan,
    validate_phase_one_shot_specification,
)
from .gsd_phase_resolver import (
    GsdPhaseResolution,
    GsdPhaseResolutionError,
    resolve_authoritative_dpc_phase,
)
from .project_phase_admission import ProjectPhaseAdmissionError, admit_project_phase
from .phase_creation import PhaseCreationError, PhaseCreationPackage, prepare_phase_creation
from .gsd_execution_workspace import (
    WorkspaceIdentity,
    WorkspaceOwnershipError,
    WorkspaceReservation,
    WorkspaceReservationController,
)
from .launcher import LaunchRequest, LaunchResult, PlatformLaunchPolicy, PlatformLauncher, StartupLaunchError
from .verification_result import VerificationResultAdapter, VerificationResultError
from .verification_lifecycle import (
    DuplicateVerificationAttempt,
    ForgeResult,
    ImmutableAttemptError,
    ProcessIdentity,
    RecoveryDenied,
    VerificationAttempt,
    VerificationAttemptStore,
    VerificationIdentity,
    VerificationLifecycle,
    VerificationLifecycleError,
)

__all__ = [
    "AgentAdapter",
    "AgentAdapterError",
    "AgentAdapterRequest",
    "CapabilityProjectionError",
    "build_skill_projection_plan",
    "AgentExecutionIdentity",
    "AgentRuntimeIdentityBridge",
    "AgentRuntimeIdentityError",
    "ProviderSessionObservation",
    "AgentEvidenceError",
    "AgentLifecycle",
    "ArtifactCollector",
    "ArtifactRecord",
    "LifecycleEvent",
    "CodeReviewError",
    "FakeCodeReviewAgent",
    "ReviewContextError",
    "ReviewPackage",
    "build_review_package",
    "CodeReviewProviderAdapter",
    "CodeReviewProviderError",
    "IndependentReviewAdapter",
    "IndependentReviewError",
    "FakeReviewCycleCoordinator",
    "ReviewCycleError",
    "ReviewLoopDecision",
    "ReviewLoopPolicyError",
    "plan_next_action",
    "CompletionDecision",
    "assess_completion",
    "RequirementGateDecision",
    "assess_requirements",
    "independent_review_required",
    "DshExecutionRecord",
    "DshRuntimeAdapter",
    "DshRuntimeError",
    "ForgeRequestAdapter",
    "ForgeRequestError",
    "RiskAdjustedForgeError",
    "RiskAdjustedForgePlan",
    "build_risk_adjusted_forge_request",
    "render_forge_manifest",
    "validate_risk_adjusted_forge_request",
    "GsdLifecycleAdapter",
    "GsdLifecycleError",
    "GsdExecutionModelError",
    "authorize_phase_execution",
    "SkillResolution",
    "resolve_skill_identity",
    "validate_execution_plan",
    "validate_phase_one_shot_specification",
    "GsdPhaseResolution",
    "GsdPhaseResolutionError",
    "resolve_authoritative_dpc_phase",
    "ProjectPhaseAdmissionError",
    "admit_project_phase",
    "PhaseCreationError",
    "PhaseCreationPackage",
    "prepare_phase_creation",
    "WorkspaceIdentity",
    "WorkspaceOwnershipError",
    "WorkspaceReservation",
    "WorkspaceReservationController",
    "LaunchRequest",
    "LaunchResult",
    "PlatformLaunchPolicy",
    "PlatformLauncher",
    "StartupLaunchError",
    "VerificationResultAdapter",
    "VerificationResultError",
    "DuplicateVerificationAttempt",
    "ForgeResult",
    "ImmutableAttemptError",
    "ProcessIdentity",
    "RecoveryDenied",
    "VerificationAttempt",
    "VerificationAttemptStore",
    "VerificationIdentity",
    "VerificationLifecycle",
    "VerificationLifecycleError",
    "HumanizerAdapter",
    "HumanizerAdapterError",
    "HumanizerRequest",
    "HumanizerBundle",
    "ConservativeHumanizerProvider",
    "RuleBasedHumanizerProvider",
    "HumanizerAdoptionDecision",
    "HumanizerArtifactError",
    "HumanizerArtifactStore",
    "StoredHumanizerArtifacts",
    "assess_humanizer_adoption",
    "HumanizerForgeCoordinator",
    "HumanizerForgeError",
    "HumanizerForgeOutcome",
    "rename_python_identifier",
    "rename_python_lambda_parameter",
    "HumanizerProfile",
    "HumanizerProfileError",
    "build_rules_for_profile",
    "load_humanizer_profile",
]
