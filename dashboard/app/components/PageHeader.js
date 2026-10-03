// The top of every page: a title, at most one short line under it, and the
// page's own live status on the right. Navigation lives in the sidebar, not
// here, so pages stop growing their own link rows.
export default function PageHeader({ eyebrow, title, sub, children }) {
  return (
    <header className="top">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {sub && <p className="sub qintro">{sub}</p>}
      </div>
      {children && <div className="status">{children}</div>}
    </header>
  );
}
