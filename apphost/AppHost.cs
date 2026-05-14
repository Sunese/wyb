var builder = DistributedApplication.CreateBuilder(args);

var pgadminEmail = builder.AddParameter("pgadmin-email", secret: true)
    .WithDescription("pgAdmin email address");
var pgadminPassword = builder.AddParameter("pgadmin-password", secret: true)
    .WithDescription("pgAdmin password");
var rabbitmqUsername = builder.AddParameter("rabbitmq-username", secret: true)
    .WithDescription("RabbitMQ username");
var rabbitmqPassword = builder.AddParameter("rabbitmq-password", secret: true)
    .WithDescription("RabbitMQ password");


builder.AddDockerComposeEnvironment("wyb")
       .WithDashboard(db => db.WithHostPort(8085))
       .ConfigureComposeFile(file =>
       {
           file.Name = "wyb";
       });

var postgres = builder.AddPostgres("postgres")
    // .WithDataVolume() // TODO: when ready, add a volume for Postgres data to ensure durability
    .WithLifetime(ContainerLifetime.Persistent)
    .WithContainerName("wyb-postgres")
    .WithPgWeb(containerName: "wyb-pgweb", configureContainer: pgWeb =>
    {
        pgWeb.WithHostPort(8080);
    });

var ledgerDb = postgres.AddDatabase("ledger-db");

var rabbit = builder.AddRabbitMQ("rabbit", rabbitmqUsername, rabbitmqPassword)
    .WithManagementPlugin()
    .WithContainerName("wyb-rabbit")
    // .WithDataVolume() // TODO: when ready, add a volume for RabbitMQ data to ensure durability
    .WithLifetime(ContainerLifetime.Persistent);

// .NET service: ledger
var ledger = builder.AddProject<Projects.Wyb_Ledger>("ledger")
    .WithReference(ledgerDb)
    .WithReference(rabbit)
    .WaitFor(ledgerDb)
    .WaitFor(rabbit);

// Go service: ingest
var ingest = builder.AddGolangApp("ingest", "../services/ingest")
    .WithHttpEndpoint(env: "PORT")
    .WithReference(rabbit)
    .WaitFor(rabbit)
    .WithEnvironment("DROP_DIR", "../../drop")
    .WithEnvironment("RAW_DIR", "../../raw");

// Python services
builder.AddPythonApp("categorize", "../services/categorize", "src/main.py")
    // .WithVirtualEnvironment("../.venv")
    .WithReference(rabbit)
    .WaitFor(rabbit)
    .WithEnvironment("PYTHONUNBUFFERED", "1");

builder.AddUvicornApp("detect", "../services/detect", "detect.main:app")
    .WithUv()
    .WithReference(rabbit)
    .WaitFor(rabbit);

// SvelteKit frontend
builder.AddViteApp("web", "../services/web")
    .WithReference(ledger)
    .WaitFor(ledger)
    .WithEnvironment("NODE_OPTIONS", "--import ./otel.js");


builder.Build().Run();