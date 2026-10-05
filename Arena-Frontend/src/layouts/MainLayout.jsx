import React, { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Menu, X, Phone, Mail } from 'lucide-react';
import Button from '../components/Button';

export const scrollToSection = (targetId) => {
  const normalizedId = targetId === 'about' ? 'workflow' : targetId;
  const el = document.getElementById(normalizedId);
  if (el) {
    const navbarHeight = 64;
    const elementPosition = el.getBoundingClientRect().top;
    const offsetPosition = elementPosition + window.pageYOffset - navbarHeight;
    window.scrollTo({
      top: Math.max(0, offsetPosition),
      behavior: 'smooth'
    });
  }
};

const navLinks = [
  { label: 'Services', targetId: 'services', href: '/#services' },
  { label: 'About', targetId: 'workflow', href: '/#workflow' },
  { label: 'Contact', targetId: 'contact', href: '/#contact' },
];

export default function MainLayout({ children }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (location.pathname === '/' && location.hash) {
      const targetId = location.hash.replace('#', '');
      const timer = setTimeout(() => {
        scrollToSection(targetId);
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [location.pathname, location.hash]);

  const handleNavClick = (e, link) => {
    e.preventDefault();
    setMobileOpen(false);

    if (location.pathname === '/') {
      scrollToSection(link.targetId);
      window.history.pushState(null, '', link.href);
    } else {
      navigate(link.href);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-white">
      {/* ─── Navbar ──────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-white/95 backdrop-blur-sm border-b border-border">
        <div className="section-container flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center">
            <img
              src="/meridian-logo.png"
              alt="Meridian AI"
              className="h-9 md:h-10 w-auto object-contain"
            />
          </Link>

          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={(e) => handleNavClick(e, link)}
                className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-primary transition-colors rounded-lg cursor-pointer"
              >
                {link.label}
              </a>
            ))}
          </nav>

          {/* CTA */}
          <div className="hidden md:flex items-center gap-3">
            <Link to="/login">
              <Button size="sm">Log In</Button>
            </Link>
          </div>

          {/* Mobile toggle */}
          <button
            className="md:hidden p-2 text-text-secondary hover:text-primary"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label="Toggle navigation menu"
          >
            {mobileOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
        </div>

        {/* Mobile Nav */}
        {mobileOpen && (
          <div className="md:hidden border-t border-border bg-white px-4 pb-4">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={(e) => handleNavClick(e, link)}
                className="block py-2.5 text-sm font-medium text-text-secondary hover:text-primary cursor-pointer"
              >
                {link.label}
              </a>
            ))}
            <Link to="/login" onClick={() => setMobileOpen(false)}>
              <Button className="w-full mt-2" size="sm">Log In</Button>
            </Link>
          </div>
        )}
      </header>

      {/* ─── Main Content ────────────────────────── */}
      <main className="flex-1">{children}</main>

      {/* ─── Footer ──────────────────────────────── */}
      <footer id="contact" className="bg-text-primary text-white scroll-mt-20">
        <div className="section-container py-16">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-12 items-start">
            {/* Brand */}
            <div>
              <div className="flex items-center mb-4">
                <img
                  src="/meridian-logo.png"
                  alt="Meridian AI"
                  className="h-11 w-auto object-contain"
                />
              </div>
              <p className="text-gray-400 text-sm leading-relaxed max-w-sm">
                Transform Data into Decisions. AI into Action.
              </p>
            </div>

            {/* Contact */}
            <div>
              <h4 className="font-semibold text-sm uppercase tracking-wider text-gray-300 mb-4">Contact</h4>
              <ul className="space-y-3 text-sm text-gray-400">
                <li>
                  <a
                    href="tel:0124-442-9900"
                    className="inline-flex items-center gap-2.5 text-gray-400 hover:text-white transition-colors"
                  >
                    <Phone size={16} className="text-primary shrink-0" />
                    <span>0124-442-9900</span>
                  </a>
                </li>
                <li>
                  <a
                    href="mailto:info@meridiansolutions.co.in"
                    className="inline-flex items-center gap-2.5 text-gray-400 hover:text-white transition-colors break-all"
                  >
                    <Mail size={16} className="text-primary shrink-0" />
                    <span>info@meridiansolutions.co.in</span>
                  </a>
                </li>
              </ul>
            </div>

            {/* Social */}
            <div>
              <h4 className="font-semibold text-sm uppercase tracking-wider text-gray-300 mb-4">Connect</h4>
              <div className="flex items-center gap-3">
                <a
                  href="https://www.linkedin.com/company/on-meridian/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="LinkedIn"
                  className="w-10 h-10 rounded-lg bg-gray-800/80 border border-gray-700/60 flex items-center justify-center text-gray-400 hover:text-white hover:bg-primary/20 hover:border-primary/50 transition-all"
                >
                  <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.88 8.56a1.68 1.68 0 0 0 1.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 0 0-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/>
                  </svg>
                </a>
                <a
                  href="https://www.instagram.com/onmeridian/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Instagram"
                  className="w-10 h-10 rounded-lg bg-gray-800/80 border border-gray-700/60 flex items-center justify-center text-gray-400 hover:text-white hover:bg-primary/20 hover:border-primary/50 transition-all"
                >
                  <svg className="w-5 h-5 fill-none stroke-current stroke-2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect width="20" height="20" x="2" y="2" rx="5" ry="5"/>
                    <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/>
                    <line x1="17.5" x2="17.51" y1="6.5" y2="6.5"/>
                  </svg>
                </a>
                <a
                  href="https://x.com/On_Meridian"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="X (formerly Twitter)"
                  className="w-10 h-10 rounded-lg bg-gray-800/80 border border-gray-700/60 flex items-center justify-center text-gray-400 hover:text-white hover:bg-primary/20 hover:border-primary/50 transition-all"
                >
                  <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                  </svg>
                </a>
                <a
                  href="https://www.youtube.com/@onmeridian"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="YouTube"
                  className="w-10 h-10 rounded-lg bg-gray-800/80 border border-gray-700/60 flex items-center justify-center text-gray-400 hover:text-white hover:bg-primary/20 hover:border-primary/50 transition-all"
                >
                  <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.5 12 3.5 12 3.5s-7.505 0-9.377.55a3.016 3.016 0 0 0-2.122 2.136C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.55 9.376.55 9.376.55s7.505 0 9.377-.55a3.016 3.016 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
                  </svg>
                </a>
              </div>
            </div>
          </div>

          <div className="border-t border-gray-800 mt-12 pt-8 flex items-center justify-between">
            <p className="text-gray-500 text-sm">&copy; 2026 All Rights Reserved.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
