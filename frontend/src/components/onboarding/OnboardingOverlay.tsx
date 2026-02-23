import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card } from "flowbite-react";
import { useOnboarding } from "../../contexts/OnboardingContext";
import type { OnboardingStep } from "../../contexts/OnboardingContext";

const STEP_TARGETS: Record<OnboardingStep, string | null> = {
  1: null,
  2: "sidebar-networks",
  3: "networks-create-button",
  4: "sidebar-nodes",
  5: "nodes-create-button",
  6: null, // final step: show Done modal only
};

export function OnboardingOverlay() {
  const { onboardingActive, step, completeStep, skip } = useOnboarding();
  const [holeRect, setHoleRect] = useState<DOMRect | null>(null);
  const navigate = useNavigate();

  const targetId = STEP_TARGETS[step];

  const updateHole = useCallback(() => {
    if (!targetId) {
      setHoleRect(null);
      return;
    }
    const el = document.querySelector(`[data-onboarding-target="${targetId}"]`);
    if (el) {
      setHoleRect(el.getBoundingClientRect());
    } else {
      setHoleRect(null);
    }
  }, [targetId]);

  useEffect(() => {
    if (!onboardingActive || !targetId) return;
    
    // Use requestAnimationFrame to avoid synchronous setState in effect
    requestAnimationFrame(() => {
      updateHole();
    });
    
    const interval = setInterval(updateHole, 200);
    window.addEventListener("resize", updateHole);
    window.addEventListener("scroll", updateHole, true);
    return () => {
      clearInterval(interval);
      window.removeEventListener("resize", updateHole);
      window.removeEventListener("scroll", updateHole, true);
    };
  }, [onboardingActive, targetId, updateHole]);

  useEffect(() => {
    if (!onboardingActive) return;
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const clicked = target.closest(`[data-onboarding-target="${targetId}"]`);
      if (clicked && targetId) {
        completeStep();
      }
    };
    document.addEventListener("click", handleClick, true);
    return () => document.removeEventListener("click", handleClick, true);
  }, [onboardingActive, targetId, completeStep]);

  if (!onboardingActive) return null;

  if (step === 1) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
        <Card className="max-w-md w-full">
          <h2 className="text-2xl font-bold mb-2">Welcome to Nebula Commander</h2>
          <p className="text-gray-700 dark:text-gray-300 mb-6">
            We&apos;ll walk you through creating your first network, then a node, and then installing the client on your device.
          </p>
          <div className="flex gap-2 justify-end">
            <Button color="gray" onClick={skip}>
              Skip
            </Button>
            <Button color="purple" onClick={completeStep}>
              Start
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (step === 6) {
    const handleDone = () => {
      completeStep();
      navigate("/client-download");
    };

    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
        <Card className="max-w-md w-full">
          <h2 className="text-2xl font-bold mb-2">Almost done</h2>
          <p className="text-gray-700 dark:text-gray-300 mb-6">
            Install ncclient on your device using the instructions for your OS (Linux, Windows, or Mac) on the Client Download page. Then run enroll with your code, then run the daemon.
          </p>
          <div className="flex gap-2 justify-end">
            <Button color="purple" onClick={handleDone}>
              Go to Client Download
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (!targetId || !holeRect) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
        <Card className="max-w-md w-full">
          <p className="text-gray-700 dark:text-gray-300 mb-4">
            {step === 2 && "Click the Networks link in the sidebar to create your first network."}
            {step === 3 && "Click the Create Network button to open the form, then fill it and submit."}
            {step === 4 && "Click the Nodes link in the sidebar to create a node."}
            {step === 5 && "Click the Create Node button to open the form, then create your node and get the enrollment code."}
          </p>
          <Button color="gray" onClick={skip}>
            Skip onboarding
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <>
      <div
        className="fixed z-[100] pointer-events-none"
        aria-hidden
        style={{
          left: holeRect.left,
          top: holeRect.top,
          width: holeRect.width,
          height: holeRect.height,
          boxShadow: "0 0 0 9999px rgba(0,0,0,0.6)",
        }}
      />
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[101] pointer-events-auto">
        <Card className="max-w-sm">
          <p className="text-sm text-gray-700 dark:text-gray-300 mb-2">
            {step === 2 && "Click the Networks link in the sidebar."}
            {step === 3 && "Click the Create Network button above."}
            {step === 4 && "Click the Nodes link in the sidebar."}
            {step === 5 && "Click the Create Node button above."}
          </p>
          <Button size="xs" color="gray" onClick={skip}>
            Skip onboarding
          </Button>
        </Card>
      </div>
    </>
  );
}
