// The top of every page: a title, one line on what the page is for, and the
// page's own live status on the right. Navigation lives in the sidebar, not
// here, so pages stop growing their own link rows.
export default function PageHeader({ eyebrow = "Agentic Edge", title, sub, children }) {
  return (
    <header className="top">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {sub && <p className="sub qintro">{sub}</p>}
      </div>
      {children && <div className="status">{children}</div>}
    </header>
  );
}
