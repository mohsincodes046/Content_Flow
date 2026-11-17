import type { Metadata } from "next";
import LegalPage from "../../components/LegalPage";

export const metadata: Metadata = { title: "Terms of Service" };

export default function Terms() {
  return <LegalPage title="Terms of Service">
    <p>By using Content Flow you agree to these terms.</p>
    <h2>Your account</h2>
    <p>Keep your login details secure. You are responsible for activity in your workspaces and for the people you invite.</p>
    <h2>Your content</h2>
    <p>You own the content you upload and publish. You give us permission to store, process and send it to the platforms you choose, only to provide the service. You must have the rights to everything you publish.</p>
    <h2>Social platforms</h2>
    <p>Publishing and insights depend on Facebook, Instagram and other platforms and their policies. You must follow their terms. Platforms may limit, delay or reject posts; we report their responses but cannot guarantee their availability.</p>
    <h2>Acceptable use</h2>
    <p>Do not use Content Flow for spam, unlawful content, or to access accounts you are not authorized to manage.</p>
    <h2>Availability and liability</h2>
    <p>We work to keep the service reliable but provide it &quot;as is&quot;. To the extent permitted by law, we are not liable for indirect losses or for actions taken by third-party platforms.</p>
    <h2>Ending use</h2>
    <p>You may stop using the service and request deletion of your data at any time. We may suspend accounts that break these terms.</p>
  </LegalPage>;
}
