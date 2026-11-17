import type { Metadata } from "next";
import Link from "next/link";
import LegalPage from "../../components/LegalPage";

export const metadata: Metadata = { title: "Privacy Policy" };

export default function Privacy() {
  return <LegalPage title="Privacy Policy">
    <p>Content Flow helps businesses and agencies plan, approve, publish and measure social media posts. This policy explains what we collect, why, and the choices you have.</p>
    <h2>What we collect</h2>
    <ul>
      <li><b>Account data:</b> your name, email address and a securely hashed password.</li>
      <li><b>Workspace data:</b> workspace names, team members and their roles, invitations.</li>
      <li><b>Content:</b> posts, captions, comments, review decisions and the images and videos you upload.</li>
      <li><b>Connected social accounts:</b> when you connect Facebook or Instagram, we receive the Pages and Instagram professional accounts you choose to add (their IDs, names and profile pictures) and access tokens that let us publish and read insights on your behalf. Tokens are encrypted at rest.</li>
      <li><b>Insights:</b> performance figures (such as views, reach and engagement) for the connected accounts and the posts we published.</li>
      <li><b>Technical data:</b> request logs and IP addresses used for security and abuse prevention.</li>
    </ul>
    <h2>How we use Facebook and Instagram data</h2>
    <p>We use the permissions you grant only to: list the Pages and Instagram accounts you can manage, publish the posts you create or schedule, and show you insights for those accounts and posts. We do not sell this data, use it for advertising, or share it with third parties except the service providers that host our application.</p>
    <h2>Sharing</h2>
    <p>Data in a workspace is visible to that workspace&apos;s members according to their roles. Clients see only content sent to them for review. Media you publish is sent to the social platforms you choose.</p>
    <h2>Retention and deletion</h2>
    <p>We keep your data while your account or workspace is active. Disconnecting a social account deletes its stored tokens immediately. You can request deletion of your data at any time; see <Link href="/data-deletion">Data deletion</Link>.</p>
    <h2>Security</h2>
    <p>Passwords are hashed, access tokens are encrypted, connections use HTTPS, and access is limited by workspace and role.</p>
    <h2>Changes</h2>
    <p>We will update this page when our practices change.</p>
  </LegalPage>;
}
