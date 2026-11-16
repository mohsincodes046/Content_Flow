import type { Metadata } from "next";
import LegalPage, { LEGAL_CONTACT } from "../../components/LegalPage";

export const metadata: Metadata = { title: "Data Deletion" };

export default function DataDeletion() {
  return <LegalPage title="Data Deletion Instructions">
    <h2>Remove a connected Facebook or Instagram account</h2>
    <ol>
      <li>Sign in to Content Flow and open <b>Social accounts</b>.</li>
      <li>Click <b>Disconnect</b> next to the account. Its stored access tokens are deleted immediately.</li>
    </ol>
    <h2>Remove Content Flow from Facebook</h2>
    <p>In Facebook, open <b>Settings &amp; privacy → Settings → Business integrations</b> (or <b>Apps and websites</b>), choose Content Flow and remove it. Facebook notifies us automatically and we delete the tokens and account details we hold for you. You receive a confirmation code you can use to check the status of the request.</p>
    <h2>Delete your whole account</h2>
    <p>Email {LEGAL_CONTACT.email} from the address you signed up with and ask us to delete your account. We delete your account, workspaces you own, their content and uploaded media within 30 days and confirm by email.</p>
  </LegalPage>;
}
