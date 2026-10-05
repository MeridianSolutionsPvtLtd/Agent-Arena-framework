import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Card from '../components/Card';
import Button from '../components/Button';
import { Input } from '../components/FormInputs';
import { useAuth } from '../context/AuthContext';
import { apiLogin, apiSignup, apiGetMe } from '../services/api';
import { DESKTOP_AGENT_ID, DESKTOP_AGENT_NAME, IS_DESKTOP_AGENT } from '../utils/desktopAgent';

export default function Login({ initialSignup = false }) {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isSignupPath = initialSignup || location.pathname === '/signup' || new URLSearchParams(location.search).get('mode') === 'signup';

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSignup, setIsSignup] = useState(isSignupPath);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setIsSignup(initialSignup || location.pathname === '/signup' || new URLSearchParams(location.search).get('mode') === 'signup');
    setError('');
  }, [location.pathname, location.search, initialSignup]);

  const handleBack = () => {
    if (isSignup) {
      navigate('/login');
    } else {
      navigate('/');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!email || !password || (isSignup && !name)) {
      setError('Please fill in all fields.');
      return;
    }

    setLoading(true);
    try {
      if (isSignup) {
        // 1. Create the account (backend returns a message, not tokens)
        await apiSignup(name, email, password);
        // 2. Log in to obtain a session
        await apiLogin(email, password);
      } else {
        await apiLogin(email, password);
      }

      // Load the real profile; fall back to what we know if /me is unavailable.
      let profile;
      try {
        profile = await apiGetMe();
      } catch {
        profile = { email, name: name || email };
      }
      login(profile);
      navigate(IS_DESKTOP_AGENT ? `/chat/${DESKTOP_AGENT_ID}` : '/dashboard');
    } catch (err) {
      setError(err.message || 'Authentication failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-section-bg relative flex items-center justify-center p-4 sm:p-6">
      {/* Top-Left Back Button */}
      <div className="absolute top-5 left-5 sm:top-8 sm:left-8 z-10">
        <button
          type="button"
          onClick={handleBack}
          className="inline-flex items-center gap-2 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer group px-3 py-1.5 rounded-lg hover:bg-white/80 border border-transparent hover:border-border/60 shadow-none hover:shadow-xs"
          aria-label="Back"
        >
          <ArrowLeft size={16} className="transition-transform group-hover:-translate-x-0.5" />
          <span>Back</span>
        </button>
      </div>

      <div className="w-full max-w-[400px]">
        {/* Logo */}
        <div className="flex items-center justify-center mb-8">
          <Link to="/" className="inline-block transition-transform hover:scale-105">
            <img
              src="/meridian-logo.png"
              alt="Meridian AI"
              className="h-11 w-auto object-contain"
            />
          </Link>
        </div>

        <Card hover={false} className="shadow-sm">
          <div className="text-center mb-6">
            <h1 className="text-xl font-bold text-text-primary">
              {isSignup ? 'Create your account' : 'Sign in to your account'}
            </h1>
            <p className="text-sm text-text-secondary mt-1">
              {IS_DESKTOP_AGENT
                ? 'Sign in to start your downloaded agent'
                : (isSignup ? 'Get started with your AI workspace' : 'Access your AI agent dashboard')}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {isSignup && (
              <Input
                label="Name"
                id="name"
                type="text"
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}

            <Input
              label="Email"
              id="email"
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="password" className="label-text !mb-0">Password</label>
                {!isSignup && (
                  <a href="#" className="text-xs font-semibold text-primary hover:underline">
                    Forgot Password?
                  </a>
                )}
              </div>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error && (
              <p className="text-xs text-red-600 font-medium">{error}</p>
            )}

            <Button type="submit" className="w-full mt-2" disabled={loading}>
              {loading ? 'Please wait...' : (isSignup ? 'Create Account' : 'Sign In')}
            </Button>
          </form>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-text-secondary text-xs uppercase tracking-wider">
                {isSignup ? 'Already have an account?' : "Don't have an account?"}
              </span>
            </div>
          </div>

          <Button
            variant="secondary"
            className="w-full"
            type="button"
            onClick={() => {
              setError('');
              navigate(isSignup ? '/login' : '/signup');
            }}
          >
            {isSignup ? 'Sign In Instead' : 'Create New Account'}
          </Button>
        </Card>
      </div>
    </div>
  );
}
