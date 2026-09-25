import { Link } from "react-router";
import { PageHead } from "../components/layout";

export default function NotFound() {
  return (
    <div className="page">
      <PageHead title="Page not found" subtitle="This route does not exist." />
      <Link className="btn" to="/overview">Go to Overview</Link>
    </div>
  );
}
