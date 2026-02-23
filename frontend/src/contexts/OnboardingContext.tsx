import { createContext, useCallback, useContext, useState } from "react";

const ONBOARDING_STORAGE_KEY = "nebula_commander_onboarding_completed";
const TOKEN_KEY = "token";

export type OnboardingStep =
  | 1 // welcome
  | 2 // sidebar-networks
  | 3 // networks-create-button
  | 4 // sidebar-nodes
  | 5 // nodes-create-button
  | 6; // sidebar-client-download / final

interface OnboardingContextValue {
  onboardingActive: boolean;
  step: OnboardingStep;
  completeStep: () => void;
  skip: () => void;
  restart: () => void;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useOnboarding() {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding must be used within OnboardingProvider");
  return ctx;
}

export function OnboardingProvider({ children }: { children: React.ReactNode }) {
  // Initialize state from localStorage - this runs only once during component mount
  const [onboardingActive, setOnboardingActive] = useState(() => {
    const alreadyCompleted = localStorage.getItem(ONBOARDING_STORAGE_KEY);
    const hasToken = localStorage.getItem(TOKEN_KEY);
    return !alreadyCompleted && !!hasToken;
  });
  const [step, setStep] = useState<OnboardingStep>(1);

  const completeStep = useCallback(() => {
    setStep((s) => {
      if (s >= 6) {
        localStorage.setItem(ONBOARDING_STORAGE_KEY, "true");
        setOnboardingActive(false);
        return 1;
      }
      return (s + 1) as OnboardingStep;
    });
  }, []);

  const skip = useCallback(() => {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, "true");
    setOnboardingActive(false);
    setStep(1);
  }, []);

  const restart = useCallback(() => {
    localStorage.removeItem(ONBOARDING_STORAGE_KEY);
    setOnboardingActive(true);
    setStep(1);
  }, []);

  const value: OnboardingContextValue = {
    onboardingActive,
    step,
    completeStep,
    skip,
    restart,
  };

  return (
    <OnboardingContext.Provider value={value}>
      {children}
    </OnboardingContext.Provider>
  );
}
