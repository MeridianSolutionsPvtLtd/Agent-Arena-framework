// ─── Services ──────────────────────────────────────────
export const services = [
  {
    id: 1,
    title: 'AI Automation',
    description: 'Streamline repetitive workflows with intelligent automation agents that learn and adapt to your business processes.',
    icon: 'Cpu',
  },
  {
    id: 2,
    title: 'Custom Agent Development',
    description: 'Purpose-built AI agents tailored to your industry-specific requirements and operational needs.',
    icon: 'Settings',
  },
  {
    id: 3,
    title: 'Cloud Integration',
    description: 'Seamless integration with existing cloud infrastructure including AWS, Azure, and Google Cloud platforms.',
    icon: 'Cloud',
  },
  {
    id: 4,
    title: 'Security & Compliance',
    description: 'Enterprise-grade security with SOC 2, GDPR, and HIPAA compliance built into every solution.',
    icon: 'Shield',
  },
];

// ─── Solutions ─────────────────────────────────────────
export const solutions = [
  {
    id: 1,
    title: 'Financial Services',
    description: 'Automated risk assessment, fraud detection, and regulatory compliance monitoring for banking and insurance.',
    industry: 'Finance',
    icon: 'TrendingUp',
  },
  {
    id: 2,
    title: 'Customer Support',
    description: 'Intelligent ticket routing, automated responses, and customer sentiment analysis for support teams.',
    industry: 'Support',
    icon: 'Headphones',
  },
  {
    id: 3,
    title: 'Operations Management',
    description: 'Supply chain optimization, predictive maintenance, and workforce planning powered by AI agents.',
    industry: 'Operations',
    icon: 'BarChart3',
  },
];

// ─── Why Choose Us ─────────────────────────────────────
export const whyChooseUs = [
  { id: 1, title: 'Enterprise-Grade Trust', description: 'SOC 2 compliant with 99.9% uptime SLA and dedicated support.' },
  { id: 2, title: 'Scalable Architecture', description: 'Built to handle millions of transactions across distributed systems.' },
  { id: 3, title: 'Seamless Integration', description: 'Connect with 200+ enterprise tools and platforms out of the box.' },
  { id: 4, title: 'Dedicated Support', description: '24/7 enterprise support with a dedicated customer success manager.' },
  { id: 5, title: 'Rapid Deployment', description: 'Go from concept to production in weeks, not months.' },
  { id: 6, title: 'Data Privacy', description: 'Your data stays yours. Full encryption and data residency controls.' },
];

// ─── Agent Catalog ─────────────────────────────────────
export const agents = [
  {
    id: 1,
    name: 'Invoice Processor',
    description: 'Automatically extracts, validates, and processes invoice data from multiple formats including PDF, email, and scanned documents.',
    industry: 'Finance',
    category: 'Automation',
    status: 'Available',
    rating: 4.8,
  },
  {
    id: 2,
    name: 'Customer Support Bot',
    description: 'Handles tier-1 support inquiries with natural language understanding, escalating complex issues to human agents.',
    industry: 'Support',
    category: 'Conversational',
    status: 'Available',
    rating: 4.6,
  },
  {
    id: 3,
    name: 'Compliance Monitor',
    description: 'Continuously monitors regulatory changes and maps them to internal policies for proactive compliance management.',
    industry: 'Legal',
    category: 'Monitoring',
    status: 'Available',
    rating: 4.9,
  },
  {
    id: 4,
    name: 'Sales Forecaster',
    description: 'Analyzes historical sales data and market signals to generate accurate quarterly and annual revenue forecasts.',
    industry: 'Sales',
    category: 'Analytics',
    status: 'Available',
    rating: 4.5,
  },
  {
    id: 5,
    name: 'HR Onboarding Assistant',
    description: 'Guides new employees through onboarding workflows, document collection, and training schedule coordination.',
    industry: 'HR',
    category: 'Workflow',
    status: 'Available',
    rating: 4.7,
  },
  {
    id: 6,
    name: 'Data Quality Auditor',
    description: 'Scans databases for inconsistencies, duplicates, and missing values with automated remediation suggestions.',
    industry: 'Operations',
    category: 'Monitoring',
    status: 'Coming Soon',
    rating: null,
  },
  {
    id: 7,
    name: 'Supply Chain Optimizer',
    description: 'Optimizes inventory levels, shipping routes, and vendor selection using real-time demand and logistics data.',
    industry: 'Operations',
    category: 'Analytics',
    status: 'Available',
    rating: 4.4,
  },
  {
    id: 8,
    name: 'Email Classifier',
    description: 'Automatically categorizes, prioritizes, and routes incoming emails to the appropriate departments and teams.',
    industry: 'Support',
    category: 'Automation',
    status: 'Available',
    rating: 4.3,
  },
  {
    id: 9,
    name: 'Risk Assessment Agent',
    description: 'Evaluates financial and operational risks using multi-factor analysis models and generates risk scoring reports.',
    industry: 'Finance',
    category: 'Analytics',
    status: 'Available',
    rating: 4.8,
  },
];

export const agentCategories = ['All', 'Automation', 'Conversational', 'Monitoring', 'Analytics', 'Workflow'];
export const agentIndustries = ['All', 'Finance', 'Support', 'Legal', 'Sales', 'HR', 'Operations'];

// ─── Dashboard Data ────────────────────────────────────
export const dashboardStats = [
  { id: 1, label: 'Active Agents', value: '12', change: '+2 this month', trend: 'up' },
  { id: 2, label: 'Tasks Completed', value: '8,431', change: '+18% vs last month', trend: 'up' },
  { id: 3, label: 'System Status', value: 'Operational', change: '99.9% uptime', trend: 'stable' },
  { id: 4, label: 'API Calls Today', value: '24,892', change: '+5% vs yesterday', trend: 'up' },
];

export const dashboardAgents = [
  { id: 1, name: 'Invoice Processor', status: 'Running', tasks: 342, lastActive: '2 min ago', health: 'Healthy' },
  { id: 2, name: 'Customer Support Bot', status: 'Running', tasks: 1205, lastActive: 'Just now', health: 'Healthy' },
  { id: 3, name: 'Compliance Monitor', status: 'Running', tasks: 89, lastActive: '5 min ago', health: 'Healthy' },
  { id: 4, name: 'Sales Forecaster', status: 'Paused', tasks: 56, lastActive: '1 hour ago', health: 'Warning' },
  { id: 5, name: 'HR Onboarding Assistant', status: 'Running', tasks: 234, lastActive: '12 min ago', health: 'Healthy' },
  { id: 6, name: 'Email Classifier', status: 'Stopped', tasks: 0, lastActive: '2 days ago', health: 'Inactive' },
];

export const activityLogs = [
  { id: 1, agent: 'Invoice Processor', action: 'Processed 15 invoices from vendor batch', time: '2 minutes ago', type: 'success' },
  { id: 2, agent: 'Customer Support Bot', action: 'Escalated ticket #4521 to human agent', time: '5 minutes ago', type: 'info' },
  { id: 3, agent: 'Compliance Monitor', action: 'New regulatory update detected — GDPR amendment', time: '12 minutes ago', type: 'warning' },
  { id: 4, agent: 'Sales Forecaster', action: 'Agent paused due to data sync delay', time: '1 hour ago', type: 'warning' },
  { id: 5, agent: 'HR Onboarding Assistant', action: 'Completed onboarding for 3 new employees', time: '2 hours ago', type: 'success' },
  { id: 6, agent: 'Invoice Processor', action: 'Validation error on invoice #INV-9982', time: '3 hours ago', type: 'error' },
];

// ─── Chat Messages ─────────────────────────────────────
export const initialMessages = [
  {
    id: 1,
    sender: 'agent',
    text: 'Hello! I\'m your Meridian AI assistant. I can help you manage agents, view reports, or answer questions about the platform. How can I assist you today?',
    time: '10:00 AM',
  },
];

// ─── Builder Integrations ──────────────────────────────
export const integrationOptions = [
  'Salesforce',
  'SAP',
  'Microsoft 365',
  'Google Workspace',
  'Slack',
  'Jira',
  'ServiceNow',
  'AWS S3',
  'Azure Blob',
  'Snowflake',
  'PostgreSQL',
  'REST API',
];
