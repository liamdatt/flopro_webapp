
# Flopro WA - Workflow Automation Platform

A Django-based web application that integrates with n8n to provide user-specific workflow automation services.

## Features

- **User Authentication**: Standard Django authentication with phone number support
- **Service Management**: Dynamic service catalog with n8n workflow templates
- **Credential Management**: Secure handling of API keys, OAuth tokens, and other credentials
- **Workflow Provisioning**: Automatic duplication of n8n templates with user-specific credentials
- **Service Toggling**: Easy switching between active services
- **n8n Integration**: Full REST API integration with n8n workflow automation platform
- **Ultimate Personal Assistant**: AI assistant that connects to Gmail and Google Calendar via Google OAuth2

## Architecture

### Models

- **Service**: Defines available services (e.g., Budget Tracker, CRM)
  - Links to n8n workflow templates
  - Contains credential schema and node access configuration
- **UserWorkflow**: Maps users to their provisioned n8n workflows and credentials
- **User**: Extended with phone_number field

### Key Components

- **n8n Client** (`core/n8n_client.py`): Handles all n8n REST API interactions
- **Provisioning** (`core/provisioning.py`): Manages workflow duplication and credential injection
- **Views**: Handle user interactions, service unlocking, and dashboard management
- **Templates**: Modern, responsive UI with service-specific forms

## Setup

### Prerequisites

- Python 3.11+
- Django 5.2+
- PostgreSQL (recommended for production) or SQLite (for development)
- n8n instance with REST API enabled
- Virtual environment

### Installation

1. **Clone and setup virtual environment:**
```bash
cd flopro_wa
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Environment variables:**
Create a `.env` file with:
```bash
# Django settings
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL)
POSTGRES_DB=flopro_wa
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# n8n Configuration
N8N_API_BASE_URL=https://your-n8n-instance.com
N8N_API_KEY=your-n8n-api-key

# Google OAuth (webapp manages Gmail/Calendar access)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

4. **Run migrations:**
```bash
python manage.py makemigrations
python manage.py migrate
```

5. **Load fixtures:**
```bash
python manage.py loaddata core/fixtures/services.json
```

6. **Create superuser:**
```bash
python manage.py createsuperuser
```

7. **Run development server:**
```bash
python manage.py runserver
```

## Usage

### For Users

1. **Register/Login**: Use Django's built-in authentication
2. **Browse Services**: View available services on the landing page
3. **Unlock Services**: Click "Unlock Service" and provide required credentials
4. **Manage Workflows**: Use the dashboard to toggle between active services
5. **Monitor**: View active workflows and their status

### For Administrators

1. **Service Management**: Use Django admin to add/edit services
2. **User Management**: Manage users and their workflows
3. **n8n Integration**: Configure n8n templates and credential schemas

## Service Configuration

### Adding a New Service

1. **Create n8n Template**: Design your workflow in n8n and note the workflow ID
2. **Define Credential Schema**: Create JSON schema for required credentials
3. **Configure Node Access**: List n8n node types that need the credential
4. **Add to Django**: Use admin interface or create fixture

Example service configuration:
```json
{
  "slug": "budget-tracker",
  "name": "Budget Tracker",
  "description": "Track expenses with Google Sheets integration",
  "icon": "fas fa-calculator",
  "template_workflow_id": 123,
  "credential_type": "googleOAuth2",
  "credential_ui_schema": {
    "client_id": {"type": "text", "label": "Client ID", "required": true},
    "client_secret": {"type": "password", "label": "Client Secret", "required": true}
  },
  "credential_node_types": ["n8n-nodes-base.googleSheets"]
}
```

## n8n Integration Details

### API Endpoints Used

- `GET /rest/workflows/{id}` - Fetch template workflows
- `POST /rest/workflows` - Create user workflows
- `PATCH /rest/workflows/{id}` - Update workflow status
- `POST /rest/credentials` - Create user credentials
- `POST /rest/workflows/{id}/activate` - Activate workflows

### Authentication

Uses `X-N8N-API-KEY` header for n8n API authentication.

### OAuth2 Flow

The webapp now manages Google OAuth directly:
1. Users authorize Gmail and Calendar access via the webapp's OAuth screen
2. Refresh tokens are stored securely in the database
3. n8n calls internal API endpoints to act on behalf of users without storing Google credentials

## Security Considerations

- **Credential Storage**: Sensitive data is stored in n8n, not Django
- **API Keys**: Use environment variables for n8n credentials
- **HTTPS**: Always use HTTPS in production
- **Permissions**: Implement proper user permissions for service access
- **Rate Limiting**: Consider implementing rate limiting for API calls

## Development

### Project Structure

```
flopro_wa/
├── core/                    # Main app
│   ├── models.py           # Service and UserWorkflow models
│   ├── views.py            # View handlers
│   ├── n8n_client.py       # n8n API client
│   ├── provisioning.py     # Workflow provisioning logic
│   ├── admin.py            # Django admin configuration
│   ├── templates/          # HTML templates
│   └── fixtures/           # Initial data
├── flopro_wa/              # Project settings
├── templates/              # Global templates
├── static/                 # Static files
└── manage.py
```

### Testing

```bash
# Run tests
python manage.py test

# Run specific app tests
python manage.py test core
```

### Deployment

1. **Environment Setup**: Configure production environment variables
2. **Database**: Use PostgreSQL in production
3. **Static Files**: Configure static file serving (nginx/Apache)
4. **n8n Instance**: Ensure n8n is properly configured and accessible
5. **SSL/TLS**: Enable HTTPS
6. **Monitoring**: Set up logging and monitoring

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Check the Django documentation
- Review n8n API documentation
- Open an issue on GitHub

---

**Note**: This is a development setup. For production deployment, ensure proper security measures, monitoring, and scalability considerations are in place.
