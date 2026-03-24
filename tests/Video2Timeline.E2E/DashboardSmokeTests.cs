using System.Text.RegularExpressions;
using Microsoft.Playwright;

namespace Video2Timeline.E2E;

[TestClass]
public sealed class DashboardSmokeTests : PageTest
{
    private static TestAppFixture _fixture = null!;

    [ClassInitialize]
    public static async Task InitializeAsync(TestContext _)
    {
        _fixture = await TestAppFixture.StartAsync();
    }

    [ClassCleanup]
    public static async Task CleanupAsync()
    {
        if (_fixture is not null)
        {
            await _fixture.DisposeAsync();
        }
    }

    [TestMethod]
    public async Task Dashboard_ShowsSetupRequirement_AndCompletedRun()
    {
        await SetLanguageAsync("en", "/");

        await Expect(Page).ToHaveURLAsync(new Regex(".*/$"));
        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "en");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Create A New Job" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Open Settings" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "run-e2e-completed" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "ZIP" })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Settings_CanToggleTerms_WithoutToken()
    {
        await SetLanguageAsync("en", "/settings");

        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "en");
        await Expect(Page.Locator("#token-state")).ToContainTextAsync("Not Saved");
        await Page.GetByLabel("Save that you confirmed the pyannote gated model terms").CheckAsync();
        await Expect(Page.Locator("#terms-state")).ToContainTextAsync("Confirmed");
        await Expect(Page.Locator("#access-state")).ToContainTextAsync("Token is not set.");
    }

    [TestMethod]
    public async Task CompletedRunDetails_ExposeZip_AndTimeline()
    {
        await SetLanguageAsync("en", $"/runs/{_fixture.CompletedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.CompletedJobId })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = _fixture.CompletedMediaId })).ToBeVisibleAsync();

        await Page.GetByRole(AriaRole.Link, new() { Name = _fixture.CompletedMediaId }).ClickAsync();
        await Expect(Page).ToHaveURLAsync(new Regex($".*/runs/{_fixture.CompletedJobId}/{_fixture.CompletedMediaId}$"));
        await Expect(Page.Locator("pre")).ToContainTextAsync("Video Timeline");
        await Expect(Page.Locator("pre")).ToContainTextAsync("public test sample");
    }

    private async Task SetLanguageAsync(string language, string returnPath)
    {
        var encoded = Uri.EscapeDataString(returnPath);
        await Page.GotoAsync($"{_fixture.BaseUrl}/set-language?lang={language}&returnUrl={encoded}");
    }
}
