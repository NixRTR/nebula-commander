import { Modal, Button } from "flowbite-react";

interface AboutModalProps {
  show: boolean;
  onClose: () => void;
}

const PAYPAL_DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=CHLZH2ZJXKQFU";
const GITHUB_NIXRTR = "https://github.com/NixRTR";
const GITHUB_NEBULA_COMMANDER = "https://github.com/NixRTR/nebula-commander";
const GITHUB_NEBULACDR = "https://github.com/NixRTR/nebulacdr.com";
const LICENSE_MIT = "https://opensource.org/licenses/MIT";
const LICENSE_GPL3 = "https://www.gnu.org/licenses/gpl-3.0.html";

export function AboutModal({ show, onClose }: AboutModalProps) {
  return (
    <Modal show={show} onClose={onClose} size="md">
      <Modal.Header>About Nebula Commander</Modal.Header>
      <Modal.Body>
        <div className="space-y-4 text-sm text-gray-700 dark:text-gray-300">
          <section>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-1">Licenses</h4>
            <ul className="list-disc list-inside space-y-0.5">
              <li>Backend — <a href={LICENSE_MIT} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">MIT</a></li>
              <li>Frontend — <a href={LICENSE_MIT} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">MIT</a></li>
              <li>ncclient — <a href={LICENSE_GPL3} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">GPL-3.0-or-later</a></li>
            </ul>
          </section>
          <section>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-1">GitHub repositories</h4>
            <ul className="list-disc list-inside space-y-0.5">
              <li>
                <a href={GITHUB_NEBULA_COMMANDER} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">
                  NixRTR/nebula-commander
                </a>
              </li>
              <li>
                <a href={GITHUB_NEBULACDR} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">
                  NixRTR/nebulacdr.com
                </a>{" "}
                (docs)
              </li>
            </ul>
          </section>
          <section>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-1">Author</h4>
            <p>William Kenny (BeardedTek)</p>
          </section>
          <section>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-1">Organization</h4>
            <p>
              <a href={GITHUB_NIXRTR} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">
                NixRTR
              </a>{" "}
              — Open-source networking and infrastructure projects, including Nebula Commander.
            </p>
          </section>
          <section>
            <h4 className="font-semibold text-gray-900 dark:text-white mb-1">Donation</h4>
            <p>
              <a href={PAYPAL_DONATE_URL} target="_blank" rel="noopener noreferrer" className="text-blue-600 dark:text-blue-400 hover:underline">
                Donate via PayPal
              </a>
            </p>
          </section>
        </div>
      </Modal.Body>
      <Modal.Footer>
        <Button color="gray" onClick={onClose}>
          Close
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
